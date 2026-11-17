/** 授权路由守卫的装配：单例 gate + 安装到 router。纯逻辑见 utils/licenseGate.js。 */
import { createLicenseGate, resolveLicenseRoute, ACTIVATE_PATH } from '../utils/licenseGate'
import { createSessionOpener, resolveAccountRoute, isLocalSessionMode } from '../utils/accountMode'

// 动态 import api，避免 router ↔ api 循环依赖
export const licenseGate = createLicenseGate({
  fetchStatus: () => import('../api').then(m => m.api.license.status())
})

export function installLicenseGuard(router) {
  router.beforeEach(async (to, from, next) => {
    const status = await licenseGate.check()
    const target = resolveLicenseRoute(to.path, status)
    if (!target) return next()
    if (target === ACTIVATE_PATH) {
      const back = to.fullPath
      return next({ path: ACTIVATE_PATH, query: back && back !== '/' && back !== '/home' ? { redirect: back } : {} })
    }
    return next(target)
  })
}

/** 受保护接口返回 LICENSE_REQUIRED 时调用：作废缓存并跳激活页 */
export function redirectToActivate(router) {
  licenseGate.invalidate()
  if (router.currentRoute.path === ACTIVATE_PATH) return
  router.push({ path: ACTIVATE_PATH, query: { redirect: router.currentRoute.fullPath } }).catch(() => {})
}

/**
 * 授权模式的账号守卫：授权码即身份，没有登录/注册。必须在授权守卫之后注册。
 * 非授权模式不处理，交给原来的登录守卫。返回 true 表示已处理（已 next）。
 */
export function installLocalSessionGuard(router, { store, hasToken, saveToken }) {
  const open = createSessionOpener({
    fetchSession: () => import('../api').then(m => m.api.auth.localSession()),
    saveToken,
    onUser: user => store.dispatch('setUser', user)
  })
  router.beforeEach(async (to, from, next) => {
    const status = licenseGate.peek()
    store.commit('SET_LOCAL_SESSION', isLocalSessionMode(status))
    const plan = resolveAccountRoute({
      toPath: to.path,
      isPublic: to.matched.some(r => r.meta.public),
      guestOnly: to.matched.some(r => r.meta.guestOnly),
      status,
      hasToken: hasToken()
    })
    if (!plan) return next()
    if (plan.needSession && !(await open())) return next(ACTIVATE_PATH) // 拿不到会话：回激活页，不放行
    if (plan.redirect) return next(plan.redirect)
    return next()
  })
}
