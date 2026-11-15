import Vue from 'vue'
import VueRouter from 'vue-router'
import AppLayout from '../layouts/AppLayout.vue'
import { installLicenseGuard } from './licenseGuard'

Vue.use(VueRouter)

// 页面按路由拆块；产品首页/登录页的 three.js 由 InkStage 再按需加载
const Landing = () => import(/* webpackChunkName: "landing" */ '../views/Landing.vue')
const AuthPage = () => import(/* webpackChunkName: "auth" */ '../views/auth/AuthPage.vue')
const ActivatePage = () => import(/* webpackChunkName: "license" */ '../views/license/ActivatePage.vue')
const Home = () => import(/* webpackChunkName: "home" */ '../views/Home.vue')
const Works = () => import(/* webpackChunkName: "works" */ '../views/Works.vue')
const Models = () => import(/* webpackChunkName: "settings" */ '../views/settings/Models.vue')
const Prompts = () => import(/* webpackChunkName: "settings" */ '../views/settings/Prompts.vue')
const Accounts = () => import(/* webpackChunkName: "settings" */ '../views/settings/Accounts.vue')
const LicenseInfo = () => import(/* webpackChunkName: "settings" */ '../views/settings/LicenseInfo.vue')
const ProjectLayout = () => import(/* webpackChunkName: "project" */ '../layouts/ProjectLayout.vue')
const NovelPage = () => import(/* webpackChunkName: "project" */ '../views/project-pages/NovelPage.vue')
const ScriptPage = () => import(/* webpackChunkName: "project" */ '../views/project-pages/ScriptPage.vue')
const StylePage = () => import(/* webpackChunkName: "project" */ '../views/project-pages/StylePage.vue')
const AssetsPage = () => import(/* webpackChunkName: "project" */ '../views/project-pages/AssetsPage.vue')
const ShotsPage = () => import(/* webpackChunkName: "project-shots" */ '../views/project-pages/ShotsPage.vue')
const VoicePage = () => import(/* webpackChunkName: "project" */ '../views/project-pages/VoicePage.vue')
const FinalPage = () => import(/* webpackChunkName: "project" */ '../views/project-pages/FinalPage.vue')
const EpisodesPage = () => import(/* webpackChunkName: "project" */ '../views/project-pages/EpisodesPage.vue')

/** 作品内页面统一拿到 pid / ep */
const projectProps = route => ({ pid: route.params.pid, ep: route.query.ep || '' })

// 旧工作台 ?tab= → 新页面
const LEGACY_TAB = { novel: 'novel', asset: 'characters', character: 'characters', shot: 'shots' }

function legacyProjectRedirect(pid, to) {
  const page = LEGACY_TAB[to.query.tab]
  const ep = to.query.video_set_id || to.query.ep
  // 旧 /projects/:id 是“视频集列表”，无 tab 时去管理剧集；旧 workbench 默认是分镜
  const fallback = to.path.endsWith('/workbench') ? 'shots' : 'episodes'
  return { path: `/projects/${pid}/${page || fallback}`, query: ep ? { ep } : {} }
}

const routes = [
  { path: '/', name: 'Landing', component: Landing, meta: { public: true, guestOnly: true } },
  // 激活页：不要求登录；授权守卫保证只有未授权时才能停留在这里
  { path: '/activate', name: 'Activate', component: ActivatePage, meta: { public: true } },
  { path: '/login', name: 'Login', component: AuthPage, meta: { public: true, guestOnly: true, mode: 'login' } },
  { path: '/register', name: 'Register', component: AuthPage, meta: { public: true, guestOnly: true, mode: 'register' } },

  {
    path: '/',
    component: AppLayout,
    children: [
      { path: 'home', name: 'Home', component: Home },
      { path: 'works', name: 'Works', component: Works },
      { path: 'settings', redirect: '/settings/models' },
      { path: 'settings/models', name: 'Models', component: Models },
      { path: 'settings/prompts', name: 'Prompts', component: Prompts },
      { path: 'settings/accounts', name: 'Accounts', component: Accounts },
      { path: 'settings/license', name: 'LicenseInfo', component: LicenseInfo }
    ]
  },

  // 旧路径兼容
  { path: '/dashboard', redirect: '/home' },
  { path: '/projects', redirect: '/works' },
  { path: '/prompts', redirect: '/settings/prompts' },
  { path: '/models', redirect: '/settings/models' },
  { path: '/accounts', redirect: '/settings/accounts' },
  { path: '/projects/:projectId/workbench', redirect: to => legacyProjectRedirect(to.params.projectId, to) },
  { path: '/projects/:projectId/assets', redirect: to => `/projects/${to.params.projectId}/characters` },

  {
    path: '/projects/:pid',
    component: ProjectLayout,
    children: [
      // 旧 /projects/:id 与 /projects/:id?tab=xxx
      { path: '', redirect: to => legacyProjectRedirect(to.params.pid, to) },
      { path: 'novel', name: 'Novel', component: NovelPage, props: projectProps },
      { path: 'script', name: 'Script', component: ScriptPage, props: projectProps },
      { path: 'style', name: 'Style', component: StylePage, props: projectProps },
      { path: 'characters', name: 'Characters', component: AssetsPage, props: r => ({ ...projectProps(r), kind: 'character' }) },
      { path: 'scenes', name: 'Scenes', component: AssetsPage, props: r => ({ ...projectProps(r), kind: 'scene' }) },
      { path: 'props', name: 'Props', component: AssetsPage, props: r => ({ ...projectProps(r), kind: 'prop' }) },
      { path: 'shots', name: 'Shots', component: ShotsPage, props: projectProps },
      { path: 'voice', name: 'Voice', component: VoicePage, props: projectProps },
      { path: 'final', name: 'Final', component: FinalPage, props: projectProps },
      { path: 'episodes', name: 'Episodes', component: EpisodesPage, props: projectProps }
    ]
  },

  { path: '*', redirect: '/home' }
]

const router = new VueRouter({
  mode: 'hash',
  routes,
  scrollBehavior: () => ({ x: 0, y: 0 })
})

// 授权守卫必须先于登录守卫注册：未授权时一律先去激活页
installLicenseGuard(router)

router.beforeEach((to, from, next) => {
  const token = localStorage.getItem('token')
  const isPublic = to.matched.some(r => r.meta.public)
  const guestOnly = to.matched.some(r => r.meta.guestOnly)

  if (!isPublic && !token) {
    next({ path: '/login', query: to.fullPath === '/home' ? {} : { redirect: to.fullPath } })
  } else if (guestOnly && token) {
    next('/home')
  } else {
    next()
  }
})

export default router
