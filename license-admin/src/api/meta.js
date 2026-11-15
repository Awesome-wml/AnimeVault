import http from './http'

export const meta = {
  /** 套餐白名单、功能点规则；失败时前端回退到 config/plans.js，所以静默 */
  get: () => http.get('/meta', { silent: true })
}
