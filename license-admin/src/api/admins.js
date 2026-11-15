import http from './http'

export const admins = {
  list: () => http.get('/admins'),
  create: (payload) => http.post('/admins', payload),
  /** patch: {role?, enabled?, password?} */
  update: (id, patch) => http.put(`/admins/${id}`, patch)
}
