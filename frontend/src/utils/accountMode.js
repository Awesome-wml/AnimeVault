/**
 * 账号模式的纯逻辑（不依赖 Vue/axios，便于单测）。
 *
 * 授权模式（后端 /api/license/status 的 local_session=true：桌面模式或 DONGAI_LICENSE_DEV=1）：
 * 授权码激活本身就是身份，没有账号登录/注册。流程：
 *   未激活 → 由授权守卫送去 /activate（本守卫不介入）；
 *   已激活（完整或只读）→ 没有 token 就自动换本地会话；登录/注册/落地页重定向到首页。
 * 非授权模式（普通网页部署）：保持原来的登录/注册流程。
 */
import { isAuthorized, isReadonly, HOME_PATH, ACTIVATE_PATH } from './licenseGate.js'

export const ACCOUNT_PAGES = ['/login', '/register']

/** 是否授权模式（用本地会话代替账号登录） */
export function isLocalSessionMode(status) {
  return !!status && status.local_session === true
}

/** 授权状态是否允许换取本地会话（完整或只读；其余一律不行） */
export function canOpenSession(status) {
  return isAuthorized(status) || isReadonly(status)
}

/**
 * 决定一次导航在“账号”这一层怎么走。
 * @returns {{redirect: string|null, needSession: boolean}}
 *   redirect：重定向目标（null 放行）；needSession：放行/重定向前要先换本地会话
 */
export function resolveAccountRoute({ toPath, isPublic, guestOnly, status, hasToken }) {
  if (!isLocalSessionMode(status)) return null // 交给原有登录守卫
  if (!canOpenSession(status)) {
    // 未激活等状态：只允许停在激活页（授权守卫已处理跳转，这里兜底）
    return { redirect: toPath === ACTIVATE_PATH ? null : ACTIVATE_PATH, needSession: false }
  }
  if (toPath === ACTIVATE_PATH) return { redirect: null, needSession: false }
  const accountPage = ACCOUNT_PAGES.includes(toPath) || guestOnly
  return { redirect: accountPage ? HOME_PATH : null, needSession: !hasToken && (!isPublic || accountPage) }
}

/**
 * 拿本地会话 token 并存起来。fetchSession 返回后端响应 {data:{token,user}}；
 * 失败（未授权等）返回 null。并发调用合并成一次。
 */
export function createSessionOpener({ fetchSession, saveToken, onUser }) {
  let pending = null
  return function open() {
    if (pending) return pending
    pending = (async () => {
      try {
        const res = await fetchSession()
        const data = (res && res.data) || res
        if (!data || !data.token) return null
        saveToken(data.token)
        if (onUser && data.user) onUser(data.user)
        return data.token
      } catch (_) {
        return null
      } finally {
        pending = null
      }
    })()
    return pending
  }
}
