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

service.interceptors.response.use(
  response => {
    return response.data
  },
  error => {
    const message = errorMessage(error)
    // 已在这里提示过，页面 catch 里再调用 utils/notify 的 toastError 时不会重复弹
    error.notified = true

    if (isAuthFormRequest(error.config)) {
      Message.error(error.response?.status === 401 ? '用户名或密码错误' : message)
    } else if (isSessionInvalid(error)) {
      localStorage.removeItem('token')
      const onLoginPage = ['/login', '/register'].includes(router.currentRoute.path)
      if (!onLoginPage && !redirectingToLogin) {
        redirectingToLogin = true
        Message.error('登录已过期，请重新登录')
        router.push({ path: '/login', query: { redirect: router.currentRoute.fullPath } })
          .catch(() => {})
          .finally(() => { redirectingToLogin = false })
      }
    } else {
      Message.error(message)
    }

    return Promise.reject(error)
  }
)

export default service

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
    save: (projectId, content) => service.post('/api/novel/save', { project_id: projectId, content }),
    // 润色：{ project_id, text, model_id, model, prompt_id, person: ''|'first'|'third' } → data { text, length, source_length }
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
    generate: (data) => service.post('/api/assets/generate', data),
    extractAll: (data) => service.post('/api/assets/extract-all', data),
    upload: (assetType, assetId, file) => {
      const formData = new FormData()
      formData.append('file', file)
      return service.post(`/api/assets/upload`, formData, {
        params: { asset_type: assetType, asset_id: assetId },
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
    split: (data) => service.post('/api/shots/split', data)
  },
  
  // 文生图
  image: {
    generate: (data) => service.post('/api/image/generate', data)
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

  prompt: {
    list: (type, category) => service.get('/api/prompts', { params: { type, category } }),
    create: (data) => service.post('/api/prompts', data),
    update: (id, data) => service.put(`/api/prompts/${id}`, data),
    delete: (id) => service.delete(`/api/prompts/${id}`)
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
    videoModels: () => service.get('/api/config/video-models')
  },

  // 静态文件地址
  staticUrl: (path) => path ? `${baseURL}/static/${path}` : null
}

// 预置风格分类库（与后端 core/style_library.py 保持一致）
export const STYLE_LIBRARY = [
  { id: 'xuanhuan', name: '玄幻', genre: '玄幻', desc: '上古大能、龙血觉醒、境界突破，少年逆天改命' },
  { id: 'mojueshi', name: '末世废土', genre: '末世', desc: '废土求生、丧尸横行、资源匮乏、人性挣扎' },
  { id: 'dushi', name: '都市', genre: '都市', desc: '现代都市职场、情感、逆袭、商战' },
  { id: 'xianxia', name: '仙侠', genre: '仙侠', desc: '御剑飞行、修仙问道、门派恩怨、渡劫飞升' },
  { id: 'xuanyi', name: '悬疑', genre: '悬疑', desc: '烧脑推理、迷雾重重、暗藏玄机、真相揭晓' },
  { id: 'gaoxiao', name: '轻松搞笑', genre: '搞笑', desc: '轻松明快、诙谐幽默、生活化、反转笑点' },
  { id: 'gufeng', name: '古风权谋', genre: '古风', desc: '古代朝堂、江湖恩怨、权谋博弈、家国天下' }
]
