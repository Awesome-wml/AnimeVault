/**
 * 唯一的 axios 实例。页面和组件只通过 src/api 里的函数发请求，不直接用 axios。
 * 拦截器统一：带 JWT、把后端 {code, message} 映射成中文提示、401 回登录页。
 */
import axios from 'axios'
import { Message } from 'element-ui'
import { mapError } from '@/utils/errors'
import { loadSession } from '@/utils/session'

export const API_BASE = process.env.VUE_APP_API_BASE || '/admin/api'

let unauthorizedHandler = null
/** 由 main.js 注册：401 时清会话并跳登录页。 */
export function onUnauthorized(fn) { unauthorizedHandler = fn }

let tokenGetter = () => { const s = loadSession(); return s ? s.token : '' }
export function setTokenGetter(fn) { tokenGetter = fn }

const http = axios.create({ baseURL: API_BASE, timeout: 20000 })

http.interceptors.request.use(config => {
  const token = tokenGetter()
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

http.interceptors.response.use(
  res => res.data,
  error => {
    const res = error.response
    const mapped = mapError({ status: res ? res.status : 0, data: res ? res.data : null, networkError: !res })
    const err = Object.assign(new Error(mapped.message), mapped, { data: res ? res.data : null })
    const cfg = error.config || {}
    // 登录接口自己的 401（密码错）不算会话失效
    const isLogin = /\/auth\/login$/.test(cfg.url || '')
    if (mapped.status === 401 && !isLogin && unauthorizedHandler) unauthorizedHandler()
    if (!cfg.silent) {
      Message.error({ message: mapped.message, duration: 4000 })
      err.notified = true
    }
    return Promise.reject(err)
  }
)

export default http
