import Vue from 'vue'
import VueRouter from 'vue-router'
import Login from '../views/Login.vue'
import Dashboard from '../views/Dashboard.vue'
import ProjectList from '../views/ProjectList.vue'
import ProjectWorkbench from '../views/ProjectWorkbench.vue'
import PromptManage from '../views/PromptManage.vue'
import AccountManage from '../views/AccountManage.vue'
import ModelManage from '../views/ModelManage.vue'

Vue.use(VueRouter)

const routes = [
  {
    path: '/',
    redirect: '/dashboard'
  },
  {
    path: '/login',
    name: 'Login',
    component: Login,
    meta: { noAuth: true }
  },
  {
    path: '/dashboard',
    name: 'Dashboard',
    component: Dashboard
  },
  {
    path: '/projects',
    name: 'ProjectList',
    component: ProjectList
  },
  {
    path: '/prompts',
    name: 'PromptManage',
    component: PromptManage
  },
  {
    path: '/accounts',
    name: 'AccountManage',
    component: AccountManage
  },
  {
    path: '/models',
    name: 'ModelManage',
    component: ModelManage
  },
  {
    path: '/projects/:projectId',
    name: 'VideoSetList',
    component: () => import('../views/VideoSetList.vue')
  },
  {
    path: '/projects/:projectId/workbench',
    name: 'ProjectWorkbench',
    component: ProjectWorkbench
  },
  // 旧独立页面路径：重定向到项目工作台对应 Tab，保持旧链接兼容
  {
    path: '/projects/:projectId/novel',
    redirect: to => ({ path: `/projects/${to.params.projectId}`, query: { tab: 'novel' } })
  },
  {
    path: '/projects/:projectId/assets',
    redirect: to => ({ path: `/projects/${to.params.projectId}`, query: { tab: 'asset' } })
  },
  {
    path: '/projects/:projectId/characters',
    redirect: to => ({ path: `/projects/${to.params.projectId}`, query: { tab: 'character' } })
  },
  {
    path: '/projects/:projectId/shots',
    redirect: to => ({ path: `/projects/${to.params.projectId}`, query: { tab: 'shot' } })
  }
]

const router = new VueRouter({
  mode: 'hash',
  routes
})

// 路由守卫
router.beforeEach((to, from, next) => {
  const token = localStorage.getItem('token')
  
  if (!to.meta.noAuth && !token) {
    next('/login')
  } else if (to.path === '/login' && token) {
    next('/dashboard')
  } else {
    next()
  }
})

export default router