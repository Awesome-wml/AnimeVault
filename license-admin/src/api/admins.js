import http from './http'

export const admins = {
  /** params: {page, page_size} */
  list: (params) => http.get('/admins', { params }),
  create: (payload) => http.post('/admins', payload),
  /** patch: {role?, enabled?, password?} */
  update: (id, patch) => http.put(`/admins/${id}`, patch)
}
