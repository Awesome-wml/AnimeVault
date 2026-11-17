/**
 * 更新状态缓存与订阅（纯逻辑，不依赖 Vue/axios，便于单测）。
 * 与授权路由守卫的 licenseGate 同构：TTL 内不重复请求、并发合并、查询失败返回 null 不缓存。
 * 额外：subscribe 让提示条和强制升级页共用一份状态；markRequired 在接口返回 UPDATE_REQUIRED 时立即切到升级页，
 * 不必等下一次轮询。
 */
export const UPDATE_STATUS_TTL_MS = 30 * 1000

export function createUpdateGate({ fetchStatus, now = Date.now, ttl = UPDATE_STATUS_TTL_MS }) {
  let cached = null
  let at = 0
  let pending = null
  const subs = new Set()

  function publish(status) {
    cached = status
    at = now()
    subs.forEach(fn => { try { fn(status) } catch (_) { /* 订阅方异常不影响其它订阅方 */ } })
  }

  async function check({ force = false } = {}) {
    if (!force && cached && now() - at < ttl) return cached
    if (pending) return pending
    pending = (async () => {
      try {
        const status = await fetchStatus()
        if (status) publish(status)
        return status || null
      } catch (_) {
        return null // 未知：不缓存，不影响使用
      } finally {
        pending = null
      }
    })()
    return pending
  }

  return {
    check,
    peek() { return cached },
    set: publish,
    subscribe(fn) { subs.add(fn); return () => subs.delete(fn) },
    /** 收到 403/426 UPDATE_REQUIRED：先把「需要升级」写进缓存（保留已有的版本信息），再强制刷新取完整信息 */
    markRequired(info = {}) {
      publish({
        ...(cached || {}),
        update_required: true,
        min_supported: info.min_supported || (cached && cached.min_supported) || null,
        required_message: info.message || (cached && cached.required_message) || ''
      })
      return check({ force: true })
    }
  }
}
