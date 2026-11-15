import http from './http'

export const requests = {
  /** params: {status?, page, page_size}；config 可传 {silent:true}（菜单角标轮询用） */
  list: (params, config) => http.get('/requests', { params, ...config }),
  /** payload: {plan, features, expires_at(Unix 秒), dev_max, note} */
  issue: (id, payload) => http.post(`/requests/${id}/issue`, payload),
  reject: (id, reason) => http.post(`/requests/${id}/reject`, { reason: reason || null })
}
