import Vue from 'vue'
import App from './App.vue'
import router from './router'
import store from './store'
import ElementUI from 'element-ui'
import 'element-ui/lib/theme-chalk/index.css'
// 样式层：变量 → 基础 → Element 主题覆盖 → 动效
import './styles/tokens.css'
import './styles/base.css'
import './styles/element-theme.css'
import './styles/motion.css'
import BaseComponents from './components/base'

Vue.config.productionTip = false

Vue.use(ElementUI)
Vue.use(BaseComponents)

new Vue({
  router,
  store,
  render: h => h(App)
}).$mount('#app')
