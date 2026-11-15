/**
 * 授权路由守卫的纯逻辑（不依赖 Vue/axios，便于单测）。
 * 规则：未授权只能进 /activate；已授权访问 /activate 跳回首页。
 * 状态查询带节流：TTL 内不重复请求；并发请求合并；查询失败（后端暂时连不上）视为未知，不拦截，由后端兜底。
 */
export const ACTIVATE_PATH = '/activate'
export const HOME_PATH = '/home'
export const STATUS_TTL_MS = 30 * 1000

export function isAuthorized(status) {
  return !!status && status.state === 'valid'
}

/** 返回需要重定向到的路径；null 表示放行 */
export function resolveLicenseRoute(toPath, status) {
  if (!status) return null
  const onActivate = toPath === ACTIVATE_PATH
  if (isAuthorized(status)) return onActivate ? HOME_PATH : null
  return onActivate ? null : ACTIVATE_PATH
}

export function createLicenseGate({ fetchStatus, now = Date.now, ttl = STATUS_TTL_MS }) {
  let cached = null
  let at = 0
  let pending = null

  async function check({ force = false } = {}) {
    if (!force && cached && now() - at < ttl) return cached
    if (pending) return pending
    pending = (async () => {
      try {
        const status = await fetchStatus()
        cached = status || null
        at = now()
        return cached
      } catch (_) {
        return null // 未知：不缓存，下次导航再试
      } finally {
        pending = null
      }
    })()
    return pending
  }

  return {
    check,
    /** 激活/注销/收到 LICENSE_REQUIRED 后调用，让下次导航重新查询 */
    invalidate() { cached = null; at = 0 },
    /** 直接写入最新状态（激活成功后） */
    set(status) { cached = status; at = now() },
    peek() { return cached }
  }
}
