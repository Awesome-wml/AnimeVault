import http from './http'

export const licenses = {
  list: (params) => http.get('/licenses', { params }),
  get: (lid) => http.get(`/licenses/${lid}`),
  events: (lid) => http.get(`/licenses/${lid}/events`),
  /** payload: {machine_code, plan, features, expires_at(Unix 秒), email, dev_max, note} */
  issue: (payload, config) => http.post('/licenses', payload, config),
  extend: (lid, expiresAt) => http.post(`/licenses/${lid}/extend`, { expires_at: expiresAt }),
  suspend: (lid) => http.post(`/licenses/${lid}/suspend`),
  resume: (lid) => http.post(`/licenses/${lid}/resume`),
  revoke: (lid) => http.post(`/licenses/${lid}/revoke`)
}
