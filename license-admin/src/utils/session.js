/**
 * 登录凭据只放 sessionStorage（关闭标签页即失效），不用 localStorage 持久化 8 小时凭据。
 * storage 可注入，便于单测。
 */
const KEY = 'dongai_license_admin_session'

function defaultStorage() {
  try { return window.sessionStorage } catch (e) { return null }
}

export function saveSession(session, storage = defaultStorage()) {
  if (!storage) return
  try { storage.setItem(KEY, JSON.stringify(session)) } catch (e) { /* 隐私模式等：忽略，仅内存有效 */ }
}

export function clearSession(storage = defaultStorage()) {
  if (!storage) return
  try { storage.removeItem(KEY) } catch (e) { /* ignore */ }
}

export function isExpired(session, nowSec = Math.floor(Date.now() / 1000)) {
  return !session || !session.token || !session.expires_at || session.expires_at <= nowSec
}

/** 读取未过期的会话；过期或损坏则清除并返回 null。 */
export function loadSession(storage = defaultStorage(), nowSec = Math.floor(Date.now() / 1000)) {
  if (!storage) return null
  let s = null
  try { s = JSON.parse(storage.getItem(KEY) || 'null') } catch (e) { s = null }
  if (isExpired(s, nowSec)) {
    clearSession(storage)
    return null
  }
  return s
}
