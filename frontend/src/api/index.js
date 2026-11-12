import axios from 'axios'
import { Message } from 'element-ui'
import router from '../router'

// 默认同源：开发时由 vue.config.js 的 devServer.proxy 转发 /api、/static，线上由 nginx 转发。
// 前后端不同源部署时用 VUE_APP_API_BASE_URL 指定后端地址。
const baseURL = process.env.VUE_APP_API_BASE_URL || ''

const service = axios.create({
  baseURL,
  timeout: 300000
})

// 请求拦截器
service.interceptors.request.use(
  config => {
    const token = localStorage.getItem('token')
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  error => {
    console.error('请求错误:', error)
    return Promise.reject(error)
  }
)

// 响应拦截器
// 登录/注册接口自己的 401 是“用户名或密码错误”，不是登录过期，不能清 token 和跳转。
const AUTH_FORM_URLS = ['/api/auth/login', '/api/auth/register']
let redirectingToLogin = false

function isAuthFormRequest(config) {
  const url = (config && config.url) || ''
  return AUTH_FORM_URLS.some(u => url.endsWith(u))
}

/** 后端 detail 可能是字符串，也可能是 FastAPI 校验错误数组 */
function errorMessage(error) {
  const detail = error.response?.data?.detail
  if (Array.isArray(detail)) return detail.map(d => d.msg || JSON.stringify(d)).join('；')
  if (detail && typeof detail === 'object') return JSON.stringify(detail)
  return detail || error.message || '请求失败'
}

function isSessionInvalid(error) {
  const status = error.response?.status
  // 未带 token 时后端返回 403「未认证」
  return status === 401 || (status === 403 && error.response?.data?.detail === '未认证')
}

/** 登录失效：清 token，跳登录页（只提示一次） */
function expireSession() {
  localStorage.removeItem('token')
  const onLoginPage = ['/login', '/register'].includes(router.currentRoute.path)
  if (!onLoginPage && !redirectingToLogin) {
    redirectingToLogin = true
    Message.error('登录已过期，请重新登录')
    router.push({ path: '/login', query: { redirect: router.currentRoute.fullPath } })
      .catch(() => {})
      .finally(() => { redirectingToLogin = false })
  }
}

service.interceptors.response.use(
  response => {
    return response.data
  },
  error => {
    const message = errorMessage(error)
    // 已在这里提示过，页面 catch 里再调用 utils/notify 的 toastError 时不会重复弹
    error.notified = true
    // 后端给的失败原因，页面要在进度区显示时读它
    error.reason = message

    if (isAuthFormRequest(error.config)) {
      Message.error(error.response?.status === 401 ? '用户名或密码错误' : message)
    } else if (isSessionInvalid(error)) {
      expireSession()
    } else {
      Message.error(message)
    }

    return Promise.reject(error)
  }
)

export default service

/**
 * POST 方式读取 SSE 流（后端 core/sse.py：data: {type: progress|done|error|ping, ...}）。
 * axios 不支持流式响应，这里用 fetch + ReadableStream；页面只调 api.xxx，不直接用它。
 *   handlers.onProgress(chars)  已接收的模型输出字符数
 * 返回 done 事件 { message, data }；HTTP 错误或 error 事件都 reject，错误对象带 reason（同 axios 拦截器）。
 */
function sseError(message, { status, notify = true } = {}) {
  const err = new Error(message)
  err.reason = message
  err.status = status
  if (notify) {
    Message.error(message)
    err.notified = true
  }
  return err
}

async function ssePost(url, body, handlers = {}) {
  const token = localStorage.getItem('token')
  let resp
  try {
    resp = await fetch(`${baseURL}${url}`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {})
      },
      body: JSON.stringify(body || {})
    })
  } catch (e) {
    throw sseError(`网络错误：${e.message || e}`)
  }
  if (!resp.ok) {
    let detail = ''
    try { detail = (await resp.json()).detail } catch (_) { /* 非 JSON 错误体 */ }
    if (Array.isArray(detail)) detail = detail.map(d => d.msg || JSON.stringify(d)).join('；')
    const fakeError = { response: { status: resp.status, data: { detail } } }
    if (isSessionInvalid(fakeError)) {
      expireSession()
      throw sseError('登录已过期，请重新登录', { status: resp.status, notify: false })
    }
    throw sseError(detail || `请求失败（${resp.status}）`, { status: resp.status })
  }
  const reader = resp.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const blocks = buffer.split('\n\n')
    buffer = blocks.pop() || ''
    for (const block of blocks) {
      const line = block.split('\n').find(l => l.startsWith('data: '))
      if (!line) continue
      let payload
      try { payload = JSON.parse(line.slice(6)) } catch (_) { continue }
      if (payload.type === 'progress') {
        // 分块任务（如长文转剧本）多带 chunk / total：第几块 / 共几块
        if (handlers.onProgress) handlers.onProgress(payload.chars || 0, payload.chunk || 0, payload.total || 0)
      } else if (payload.type === 'done') {
        return payload
      } else if (payload.type === 'error') {
        throw sseError(payload.message || '生成失败')
      }
    }
  }
  throw sseError('连接中断，没有收到完成结果')
}

// API接口
export const api = {
  // 认证
  auth: {
    register: (data) => service.post('/api/auth/register', data),
    login: (data) => service.post('/api/auth/login', data),
    getMe: () => service.get('/api/auth/me'),
    updateConfig: (data) => service.put('/api/auth/config', data),
    getConfig: () => service.get('/api/auth/config')
  },
  
  // 项目
  project: {
    create: (data) => service.post('/api/projects', data),
    list: () => service.get('/api/projects'),
    get: (id) => service.get(`/api/projects/${id}`),
    update: (id, data) => service.put(`/api/projects/${id}`, data),
    delete: (id) => service.delete(`/api/projects/${id}`)
  },
  
  // 小说
  novel: {
    // AI 写小说（SSE 流）：EventSource 不能带请求头，token 走查询参数
    generateStreamUrl: (params) => `${baseURL}/api/novel/generate?${new URLSearchParams(params)}`,
    // 正文放请求体：放在 URL 里，几千字就会超出请求头上限（431）
    save: (projectId, setId, content) => service.post('/api/novel/save', { project_id: projectId, video_set_id: setId || '', content }),
    // 润色：{ project_id, video_set_id, text, model_id, model, prompt_id, person: ''|'first'|'third' } → data { text, length, source_length }
    // 只返回结果，不覆盖原文；用户确认后再 save
    polish: (data) => service.post('/api/novel/polish', data)
  },
  
  // 角色
  character: {
    create: (data) => service.post('/api/characters', data),
    list: (projectId) => service.get('/api/characters', { params: { project_id: projectId } }),
    update: (id, data) => service.put(`/api/characters/${id}`, data),
    delete: (id) => service.delete(`/api/characters/${id}`),
    extract: (data) => service.post('/api/characters/extract', data)
  },
  
  // 道具
  prop: {
    create: (data) => service.post('/api/props', data),
    list: (projectId) => service.get('/api/props', { params: { project_id: projectId } }),
    update: (id, data) => service.put(`/api/props/${id}`, data),
    delete: (id) => service.delete(`/api/props/${id}`),
    extract: (data) => service.post('/api/props/extract', data)
  },
  
  // 场景
  scene: {
    create: (data) => service.post('/api/scenes', data),
    list: (projectId) => service.get('/api/scenes', { params: { project_id: projectId } }),
    update: (id, data) => service.put(`/api/scenes/${id}`, data),
    delete: (id) => service.delete(`/api/scenes/${id}`),
    extract: (data) => service.post('/api/scenes/extract', data)
  },
  
  // 资产参考图（角色三视图/道具图/场景图）
  asset: {
    /** { asset_type, asset_id, style, model_id?, model?（文生图预设/子模型）, prompt_id?（角色三视图提示词）,
     *    form_index?（角色：第几个形态的三视图，从 0 起）, view_index?（场景：第几个视角的场景图，从 0 起） }
     *    → data { img_path, form_index, view_index } */
    generate: (data) => service.post('/api/assets/generate', data),
    /** 全量提取（SSE）：onProgress(已接收字符数)；resolve { message, data: { characters, props, scenes } } */
    extractAll: (data, onProgress) => ssePost('/api/assets/extract-all', data, { onProgress }),
    /** index：角色上传到第几个形态 / 场景上传到第几个视角（从 0 起），道具不传 */
    upload: (assetType, assetId, file, index) => {
      const formData = new FormData()
      formData.append('file', file)
      const params = { asset_type: assetType, asset_id: assetId }
      if (index != null) params[assetType === 'scene' ? 'view_index' : 'form_index'] = index
      return service.post(`/api/assets/upload`, formData, {
        params,
        headers: { 'Content-Type': 'multipart/form-data' }
      })
    }
  },
  
  // 分镜
  shot: {
    create: (data) => service.post('/api/shots', data),
    list: (projectId, videoSetId) => service.get('/api/shots', { params: { project_id: projectId, video_set_id: videoSetId || '' } }),
    update: (id, data) => service.put(`/api/shots/${id}`, data),
    delete: (id) => service.delete(`/api/shots/${id}`),
    // 长文分块逐块调用大模型，可能十几分钟；SSE 流式推进度，不用全局超时
    /** 拆分镜（SSE，覆盖旧分镜）：onProgress(chars, 第几块, 共几块)；返回 done { message, data } */
    split: (data, onProgress) => ssePost('/api/shots/split', data, { onProgress })
  },

  // 剧本（小说 → 分场剧本；有剧本时资产提取、拆分镜都基于剧本）
  script: {
    /** 转剧本（SSE，覆盖旧剧本）：{ project_id, novel_text, model_id, model, prompt_id, person, target_seconds }，
     *  onProgress(已接收字符数, 第几块, 共几块)；长文按段落分块转换，块数为 1 时后两个参数为 0 或 1 */
    convert: (data, onProgress) => ssePost('/api/scripts/convert', data, { onProgress }),
    /** → data { scripts: [{ id, scene_no, location, time, characters, dialogues: [{ speaker, line, kind }], action, beat, summary }] }
     *  kind：narration 旁白 / inner 心声 / onscreen 当面 / offscreen 画外 */
    list: (projectId, setId) => service.get('/api/scripts/list', { params: { project_id: projectId, video_set_id: setId || '' } }),
    create: (data) => service.post('/api/scripts', data),
    update: (id, data) => service.put(`/api/scripts/${id}`, data),
    delete: (id) => service.delete(`/api/scripts/${id}`)
  },
  
  // 文生图（分镜画面）
  image: {
    /** 单张首帧（旧格式镜头）：{ shot_id, prompt, neg_prompt, model_id?, model? } → data { img_path } */
    generate: (data) => service.post('/api/image/generate', data),
    /** 视频段的 2×2 四格分镜图（方图，作视频参考图）：{ shot_id, model_id?, model?, storyboard_prompt? }
     *  → data { storyboard_path, storyboard_prompt, prompt, size } */
    storyboard: (data) => service.post('/api/image/storyboard', data, { timeout: 5 * 60 * 1000 })
  },
  
  // TTS
  tts: {
    getVoices: () => service.get('/api/tts/voices'),
    generate: (data) => service.post('/api/tts/generate', data),
    autoAssign: (projectId) => service.post('/api/tts/auto-assign', null, { params: { project_id: projectId } }),
    exportSrt: (projectId) => service.post('/api/tts/srt/export', { project_id: projectId }),
    // 用 window.open 下载，带不了请求头，token 走查询参数（同 AI 写小说的 SSE）
    downloadSrt: (projectId) => `${baseURL}/api/tts/srt/download/${projectId}?${new URLSearchParams({ token: localStorage.getItem('token') || '' })}`
  },
  
  // 视频生成（豆包自动化）
  video: {
    // 生成进度推送（SSE）
    eventsUrl: (projectId) => `${baseURL}/api/video/events/${projectId}`,
    getAccountStatus: () => service.get('/api/video/accounts/status'),
    listAccounts: () => service.get('/api/video/accounts'),
    addAccount: (data) => service.post('/api/video/accounts', data),
    updateAccount: (id, data) => service.put(`/api/video/accounts/${id}`, data),
    deleteAccount: (id) => service.delete(`/api/video/accounts/${id}`),
    renameAccount: (id, name) => service.put(`/api/video/accounts/${id}/rename`, { name }),
    checkLogin: (id) => service.post(`/api/video/accounts/${id}/check-login`),
    launchLogin: (id) => service.post(`/api/video/accounts/${id}/launch-login`),
    generateBatch: (projectId, limit = 0, parallel = false) => service.post('/api/video/generate/batch', null, {
      params: { project_id: projectId, limit: limit, parallel: parallel }
    }),
    generateSingle: (shotId, accountId) => service.post('/api/video/generate/single', null, {
      params: { shot_id: shotId, account_id: accountId }
    }),
    uploadShotVideo: (shotId, file) => {
      const fd = new FormData()
      fd.append('file', file)
      return service.post(`/api/video/shots/${shotId}/upload-video`, fd, {
        headers: { 'Content-Type': 'multipart/form-data' }
      })
    },
    fetchShotVideoByUrl: (shotId, url) =>
      service.post(`/api/video/shots/${shotId}/url-video`, { url }),
    launchDoubao: (accountId, url) =>
      service.post(`/api/video/accounts/${accountId}/launch`, { url: url || '' })
  },

  // 提示词：列表里内置记录带 is_builtin / has_update（代码已有新版本）；内置只能改 content、不能删
  prompt: {
    /** 只读：展示 core/prompts/*.json 里的提示词 → { data, categories, read_only, note } */
    list: (type, category) => service.get('/api/prompts', { params: { type, category } })
  },

  // 模型预设管理
  model: {
    list: () => service.get('/api/models'),
    create: (data) => service.post('/api/models', data),
    update: (id, data) => service.put(`/api/models/${id}`, data),
    delete: (id) => service.delete(`/api/models/${id}`),
    setDefault: (id) => service.post(`/api/models/${id}/default`)
  },
  
  // 剧集（后端称“视频集” video-set）
  videoSet: {
    list: (projectId) => service.get('/api/video-set/list', { params: { project_id: projectId } }),
    create: (projectId, name) => service.post('/api/video-set/create', { project_id: projectId, name }),
    rename: (setId, name) => service.post('/api/video-set/rename', { name }, { params: { set_id: setId } }),
    delete: (setId) => service.delete('/api/video-set/delete', { params: { set_id: setId } })
  },

  // 导出
  export: {
    // 写剪映草稿并打开剪映；返回 { ok, msg }（ok=false 时 msg 为原因，HTTP 仍是 200）
    jianying: (projectId, videoSetId) => service.get('/api/video/export/jianying', {
      params: { project_id: projectId, video_set_id: videoSetId || '' }
    })
  },

  // 系统配置
  config: {
    // 视频模型（Seedance 系列）：data { models: [{ key, name, note, max_duration, min_duration, cost_multiplier, reference_types }], default }
    videoModels: () => service.get('/api/config/video-models'),
    // 风格库（媒介 + 题材，backend/core/style_library.py）：data { medium_groups, mediums, genres, default_medium, legacy_styles }
    styleLibrary: () => service.get('/api/config/style-library')
  },

  // 静态文件地址
  staticUrl: (path) => path ? `${baseURL}/static/${path}` : null
}
