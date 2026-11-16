import http from './http'

export const licenses = {
  list: (params) => http.get('/licenses', { params }),
  get: (lid) => http.get(`/licenses/${lid}`),
  /** params: {page, page_size, order}，服务端默认按时间倒序 */
  events: (lid, params) => http.get(`/licenses/${lid}/events`, { params }),
  /** payload: {machine_code, plan, features, expires_at(Unix 秒), email, dev_max, note} */
  issue: (payload, config) => http.post('/licenses', payload, config),
  extend: (lid, expiresAt) => http.post(`/licenses/${lid}/extend`, { expires_at: expiresAt }),
  suspend: (lid) => http.post(`/licenses/${lid}/suspend`),
  resume: (lid) => http.post(`/licenses/${lid}/resume`),
  revoke: (lid) => http.post(`/licenses/${lid}/revoke`),
  devices: (lid) => http.get(`/licenses/${lid}/devices`),
  /** 踢下线：对方下次续租会收到 LICENSE_SESSION_CONFLICT，需要用授权码重新激活 */
  kick: (lid) => http.post(`/licenses/${lid}/kick`),
  unbindDevice: (lid, did) => http.post(`/licenses/${lid}/devices/${did}/unbind`)
}
