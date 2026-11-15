/** 授权路由守卫的装配：单例 gate + 安装到 router。纯逻辑见 utils/licenseGate.js。 */
import { createLicenseGate, resolveLicenseRoute, ACTIVATE_PATH } from '../utils/licenseGate'

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
