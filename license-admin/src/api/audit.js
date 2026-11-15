import http from './http'

export const audit = {
  list: (params) => http.get('/audit', { params })
}
