import Vue from 'vue'
import App from './App.vue'
import router from './router'
import store from './store'
import ElementUI from 'element-ui'
import 'element-ui/lib/theme-chalk/index.css'
import './styles/tokens.css'
import './styles/base.css'
import './styles/element-theme.css'
import BaseComponents from './components/base'
import { onUnauthorized } from './api'

Vue.config.productionTip = false
Vue.use(ElementUI)
Vue.use(BaseComponents)

// 会话失效（401 或 8 小时到期）：清凭据回登录页
function backToLogin(expired) {
  store.dispatch('logout')
  const cur = router.currentRoute
  if (cur.path !== '/login') {
    router.replace({ path: '/login', query: { redirect: cur.fullPath, ...(expired ? { expired: '1' } : {}) } })
  }
}
onUnauthorized(() => backToLogin(true))

new Vue({ router, store, render: h => h(App) }).$mount('#app')
