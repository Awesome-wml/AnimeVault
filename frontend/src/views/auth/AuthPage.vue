<template>
  <div class="auth">
    <section class="auth__art">
      <InkStage variant="side" />
      <router-link to="/" class="auth__brand serif">DongAI</router-link>
      <p class="auth__title vt serif">把小说，<br>拍成短剧。</p>
    </section>

    <main class="auth__main">
      <form class="auth__form" novalidate @submit.prevent="submit">
        <nav aria-label="登录或注册" class="auth__tabs">
          <router-link
            v-for="tab in tabs"
            :key="tab.mode"
            :to="{ path: tab.path, query: $route.query }"
            replace
            class="auth__tab"
            :class="{ 'is-current': tab.mode === mode }"
            :aria-current="tab.mode === mode ? 'page' : null"
          >{{ tab.label }}</router-link>
        </nav>

        <FormField label="用户名" :error="errors.username">
          <el-input v-model.trim="form.username" autocomplete="username" :placeholder="isRegister ? '3–50 个字符' : ''" />
        </FormField>
        <FormField label="密码" :error="errors.password">
          <el-input
            v-model="form.password"
            type="password"
            :autocomplete="isRegister ? 'new-password' : 'current-password'"
            :placeholder="isRegister ? '至少 6 位' : ''"
          />
        </FormField>
        <FormField v-if="isRegister" label="确认密码" :error="errors.confirm">
          <el-input v-model="form.confirm" type="password" autocomplete="new-password" />
        </FormField>

        <BaseButton type="submit" variant="primary" size="lg" block :loading="loading" class="auth__submit">
          {{ isRegister ? '注册并开始' : '登录' }}
        </BaseButton>
      </form>
    </main>
  </div>
</template>

<script>
/** 登录 / 注册（同一组件，由路由 meta.mode 区分，顶部 tab 切换路由） */
import { api } from '@/api'
import InkStage from '@/components/ink/InkStage.vue'
import { toastError } from '@/utils/notify'

const TABS = [
  { mode: 'login', label: '登录', path: '/login' },
  { mode: 'register', label: '注册', path: '/register' }
]

function emptyForm() {
  return { username: '', password: '', confirm: '' }
}

export default {
  name: 'AuthPage',
  components: { InkStage },
  data() {
    return { tabs: TABS, form: emptyForm(), errors: {}, loading: false }
  },
  computed: {
    mode() { return this.$route.meta.mode || 'login' },
    isRegister() { return this.mode === 'register' }
  },
  watch: {
    mode() {
      this.errors = {}
      this.form.confirm = ''
    }
  },
  methods: {
    validate() {
      const { username, password, confirm } = this.form
      const e = {}
      if (!username) e.username = '请输入用户名'
      else if (this.isRegister && (username.length < 3 || username.length > 50)) e.username = '用户名长度 3–50 个字符'
      if (!password) e.password = '请输入密码'
      else if (this.isRegister && password.length < 6) e.password = '密码至少 6 位'
      if (this.isRegister && !e.password && confirm !== password) e.confirm = '两次输入的密码不一致'
      this.errors = e
      return Object.keys(e).length === 0
    },
    async submit() {
      if (this.loading || !this.validate()) return
      this.loading = true
      try {
        const payload = { username: this.form.username, password: this.form.password }
        const res = await (this.isRegister ? api.auth.register(payload) : api.auth.login(payload))
        localStorage.setItem('token', res.data.token)
        this.$store.dispatch('setUser', res.data.user)
        const redirect = this.$route.query.redirect
        this.$router.replace(typeof redirect === 'string' && redirect.startsWith('/') ? redirect : '/home')
      } catch (e) {
        // 请求错误由拦截器给出（登录 401 →“用户名或密码错误”），这里只补非请求异常
        toastError(e, this.isRegister ? '注册失败' : '登录失败')
      } finally {
        this.loading = false
      }
    }
  }
}
</script>

<style scoped>
.auth {
  min-height: 100vh;
  display: flex;
  flex-wrap: wrap;
}
.auth__art {
  position: relative;
  flex: 3 1 420px;
  min-width: 0;
  min-height: 320px;
  padding: 32px 40px;
  display: flex;
  flex-direction: column;
  gap: 32px;
  overflow: hidden;
}
.auth__art > :not(.ink-stage) { position: relative; z-index: 1; }
.auth__brand { align-self: flex-start; font-size: 20px; font-weight: 700; }
.auth__title {
  align-self: flex-start;
  margin-top: 16px;
  font-size: 36px;
  font-weight: 700;
  line-height: 1.5;
  height: 300px;
}

.auth__main {
  flex: 2 1 360px;
  min-width: 0;
  padding: 40px 48px;
  display: flex;
  align-items: center;
  justify-content: center;
}
.auth__form { width: 100%; max-width: 360px; display: flex; flex-direction: column; gap: 16px; }
.auth__tabs { display: flex; gap: 24px; margin-bottom: 8px; }
.auth__tab {
  display: flex;
  align-items: center;
  min-height: 44px;
  font-size: 16px;
  color: var(--ink-muted);
  text-underline-offset: 8px;
}
.auth__tab.is-current { color: var(--ink); font-weight: 600; text-decoration: underline; }
.auth__submit { margin-top: 8px; }

@media (max-width: 760px) {
  .auth__art { flex-basis: 100%; min-height: 260px; padding: 20px; gap: 16px; }
  .auth__title { font-size: 28px; height: 200px; margin-top: 0; }
  .auth__main { flex-basis: 100%; padding: 24px 20px 40px; }
}
</style>
