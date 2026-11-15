/**
 * 授权接口（后端 api/license.py）。不需要登录。
 * 纯函数与错误映射写在这里（不依赖 axios/Element），由 api/index.js 注入 service 后挂到 api.license。
 *
 * 后端错误体：{ code, message, detail }；受保护接口未授权时 403 { code: 'LICENSE_REQUIRED', state }。
 */
export const LICENSE_REQUIRED = 'LICENSE_REQUIRED'

export const LICENSE_ERROR_MESSAGES = {
  LICENSE_INVALID: '授权码无效，请检查是否复制完整',
  LICENSE_MACHINE_MISMATCH: '这不是本机的授权码，请确认发给我们的是本机的机器码',
  LICENSE_EXPIRED: '授权码已过期，请联系我们续期',
  MACHINE_CODE_UNAVAILABLE: '无法读取本机硬件信息，请联系我们',
  LICENSE_REQUIRED: '请先激活授权'
}

const NETWORK_MESSAGE = '无法连接到本机服务，请稍后重试'
const FALLBACK_MESSAGE = '激活失败，请稍后重试'

/** 从 axios 错误里取后端 code */
export function licenseErrorCode(error) {
  const data = error && error.response && error.response.data
  return (data && typeof data.code === 'string' && data.code) || ''
}

/** 激活失败时展示给用户的中文提示：按 code 映射，未知 code 用后端 message，网络错误单独提示 */
export function licenseErrorMessage(error) {
  const code = licenseErrorCode(error)
  if (code && LICENSE_ERROR_MESSAGES[code]) return LICENSE_ERROR_MESSAGES[code]
  if (error && !error.response) return NETWORK_MESSAGE
  const data = error && error.response && error.response.data
  return (data && typeof data.message === 'string' && data.message) || FALLBACK_MESSAGE
}

/** 是否「受保护接口因未授权被拒」（axios 错误） */
export function isLicenseRequired(error) {
  return !!error && !!error.response && error.response.status === 403 && licenseErrorCode(error) === LICENSE_REQUIRED
}

/** 请求地址是否属于授权接口（这些接口的错误由激活页自己展示，拦截器不弹提示） */
export function isLicenseUrl(url) {
  return /\/api\/license(\/|$)/.test(url || '')
}

export function createLicenseApi(service) {
  return {
    machineCode: () => service.get('/api/license/machine-code'),
    status: () => service.get('/api/license/status'),
    activate: code => service.post('/api/license/activate', { code }),
    deactivate: () => service.post('/api/license/deactivate')
  }
}
