<template>
  <div class="login">
    <div class="login__card">
      <h1 class="login__title">DongAI 授权管理</h1>
      <p class="muted small login__sub">仅限内部管理员使用</p>
      <el-alert v-if="expired" type="info" :closable="false" show-icon title="登录已过期，请重新登录" class="login__alert" data-testid="login-expired" />
      <el-alert v-if="error" :type="locked ? 'warning' : 'error'" :closable="false" show-icon :title="error"
                class="login__alert" data-testid="login-error" />
      <el-form label-position="top" @submit.native.prevent="submit">
        <el-form-item label="用户名">
          <el-input v-model="username" autocomplete="username" autofocus data-testid="login-username" />
        </el-form-item>
        <el-form-item label="密码">
          <el-input v-model="password" type="password" autocomplete="current-password" show-password
                    data-testid="login-password" @keyup.enter.native="submit" />
        </el-form-item>
        <el-button type="primary" class="login__btn" :loading="loading" :disabled="locked || !username || !password"
                   data-testid="login-submit" @click="submit">
          {{ locked ? `已锁定（${waitText}）` : '登录' }}
        </el-button>
      </el-form>
    </div>
  </div>
</template>

<script>
import { formatWait } from '@/utils/errors'

export default {
  name: 'Login',
  data() {
    return { username: '', password: '', loading: false, error: '', lockedUntil: 0, now: Date.now(), tick: null }
  },
  computed: {
    expired() { return this.$route.query.expired === '1' },
    locked() { return this.lockedUntil > this.now },
    waitText() { return formatWait((this.lockedUntil - this.now) / 1000) }
  },
  beforeDestroy() { clearInterval(this.tick) },
  methods: {
    async submit() {
      if (this.loading || this.locked || !this.username || !this.password) return
      this.loading = true
      this.error = ''
      try {
        await this.$store.dispatch('login', { username: this.username.trim(), password: this.password })
        const redirect = this.$route.query.redirect
        this.$router.replace(typeof redirect === 'string' && redirect.startsWith('/') ? redirect : '/')
      } catch (e) {
        this.error = e.message || '登录失败'
        this.password = ''
        if (e.code === 'LOGIN_LOCKED') this.startLock(e.retryAfter || 900)
      } finally {
        this.loading = false
      }
    },
    startLock(seconds) {
      this.now = Date.now()
      this.lockedUntil = this.now + seconds * 1000
      clearInterval(this.tick)
      this.tick = setInterval(() => {
        this.now = Date.now()
        if (!this.locked) { clearInterval(this.tick); this.error = '' }
      }, 1000)
    }
  }
}
</script>

<style scoped>
.login { min-height: 100vh; display: flex; align-items: center; justify-content: center; padding: 24px 16px; background: var(--paper); }
.login__card { width: 380px; max-width: 100%; padding: 36px 32px 32px; background: var(--surface); border: 1px solid var(--line); border-radius: 12px; }
.login__title { font-family: var(--font-serif); font-size: 26px; font-weight: 700; }
.login__sub { margin: 4px 0 20px; }
.login__alert { margin-bottom: 16px; }
.login__btn { width: 100%; }
</style>
