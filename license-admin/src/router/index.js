import Vue from 'vue'
import VueRouter from 'vue-router'
import store from '@/store'
import { can } from '@/config/roles'
import { isExpired } from '@/utils/session'

Vue.use(VueRouter)

const routes = [
  { path: '/login', name: 'login', component: () => import('@/views/Login.vue'), meta: { public: true, title: '登录' } },
  {
    path: '/',
    component: () => import('@/layouts/AdminLayout.vue'),
    redirect: '/licenses',
    children: [
      { path: 'licenses', name: 'licenses', component: () => import('@/views/LicenseList.vue'), meta: { perm: 'license.read', title: '授权管理' } },
      { path: 'requests', name: 'requests', component: () => import('@/views/RequestList.vue'), meta: { perm: 'request.manage', title: '申请单' } },
      { path: 'audit', name: 'audit', component: () => import('@/views/AuditLog.vue'), meta: { perm: 'audit.read', title: '审计日志' } },
      { path: 'admins', name: 'admins', component: () => import('@/views/AdminList.vue'), meta: { perm: 'admin.manage', title: '管理员管理' } }
    ]
  },
  { path: '*', redirect: '/' }
]

const router = new VueRouter({ mode: 'history', routes })

router.beforeEach((to, from, next) => {
  document.title = (to.meta.title ? to.meta.title + ' - ' : '') + 'DongAI 授权管理'
  if (to.meta.public) return next()
  if (isExpired({ token: store.state.token, expires_at: store.state.expiresAt })) {
    const hadToken = !!store.state.token
    store.dispatch('logout')
    const query = { redirect: to.fullPath }
    if (hadToken) query.expired = '1'
    return next({ path: '/login', query })
  }
  const perm = to.meta.perm
  if (perm && !can(store.getters.role, perm)) return next('/licenses')
  next()
})

export default router
