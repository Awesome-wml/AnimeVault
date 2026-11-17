/**
 * 更新检查接口（后端 api/update.py，属于授权白名单：未激活、需要升级时也能访问）。
 * 纯函数与错误映射写在这里（不依赖 axios/Element），由 api/index.js 注入 service 后挂到 api.update。
 *
 * 强制升级时，除 /api/license/*、/api/update/*、/health 外的接口一律 403 { code: 'UPDATE_REQUIRED', min_supported, message }；
 * 授权服务对过旧版本的激活/续租返回 426（同 code）。
 */
export const UPDATE_REQUIRED = 'UPDATE_REQUIRED'

function errorData(error) {
  return (error && error.response && error.response.data) || {}
}

/** 是否「因版本过低被拒」（受保护接口 403，或激活/续租 426） */
export function isUpdateRequired(error) {
  const res = error && error.response
  return !!res && (res.status === 403 || res.status === 426) && errorData(error).code === UPDATE_REQUIRED
}

/** 请求地址是否属于更新接口（错误由更新条/升级页自己展示，拦截器不弹提示） */
export function isUpdateUrl(url) {
  return /\/api\/update(\/|$)/.test(url || '')
}

/** 从 UPDATE_REQUIRED 错误里取出升级要求，给 updateGate 用 */
export function requiredInfoFromError(error) {
  const d = errorData(error)
  return {
    min_supported: typeof d.min_supported === 'string' ? d.min_supported : null,
    message: typeof d.message === 'string' ? d.message : ''
  }
}

export function createUpdateApi(service) {
  return {
    status: () => service.get('/api/update/status'),
    check: () => service.post('/api/update/check')
  }
}
