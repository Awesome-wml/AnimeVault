import http from './http'

export const auth = {
  /** 登录页自己展示错误（含锁定提示），所以 silent。 */
  login: (username, password) => http.post('/auth/login', { username, password }, { silent: true }),
  me: () => http.get('/auth/me')
}
