<template>
  <div class="layout">
    <aside class="layout__side">
      <div class="layout__brand">DongAI<span class="muted small"> 授权管理</span></div>
      <nav class="layout__nav" aria-label="主菜单">
        <router-link v-for="m in menu" :key="m.path" :to="m.path" class="layout__link" active-class="is-active"
                     :data-testid="'menu-' + m.path.slice(1)">
          <i :class="m.icon"></i>{{ m.title }}
        </router-link>
      </nav>
    </aside>
    <div class="layout__body">
      <header class="layout__top">
        <span class="muted small">{{ $route.meta.title }}</span>
        <div class="layout__user" data-testid="current-admin">
          <i class="el-icon-user"></i>
          <span class="layout__name">{{ admin.username }}</span>
          <el-tag size="mini" class="layout__role" data-testid="current-role">{{ roleText }}</el-tag>
          <el-button type="text" data-testid="logout" @click="logout">退出登录</el-button>
        </div>
      </header>
      <main class="layout__main"><router-view :key="$route.path" /></main>
    </div>
  </div>
</template>

<script>
import { menuFor, roleLabel } from '@/config/roles'

export default {
  name: 'AdminLayout',
  data() { return { timer: null } },
  computed: {
    admin() { return this.$store.state.admin || {} },
    roleText() { return roleLabel(this.admin.role) },
    menu() { return menuFor(this.admin.role) }
  },
  mounted() {
    // 凭据到期（8 小时）自动回登录页
    const ms = this.$store.state.expiresAt * 1000 - Date.now()
    if (ms > 0 && ms < 2 ** 31) this.timer = setTimeout(() => this.leave(true), ms)
  },
  beforeDestroy() { clearTimeout(this.timer) },
  methods: {
    logout() { this.leave(false) },
    leave(expired) {
      this.$store.dispatch('logout')
      this.$router.replace({ path: '/login', query: expired ? { expired: '1' } : {} })
    }
  }
}
</script>

<style scoped>
.layout { min-height: 100vh; display: flex; background: var(--paper); }
.layout__side { flex: none; width: var(--side-w); background: var(--side); border-right: 1px solid var(--line); padding: 20px 12px; }
.layout__brand { font-family: var(--font-serif); font-size: 20px; font-weight: 700; padding: 0 10px 18px; }
.layout__nav { display: flex; flex-direction: column; gap: 2px; }
.layout__link {
  display: flex; align-items: center; gap: 8px; min-height: 38px; padding: 0 10px;
  border-radius: var(--radius-nav); color: var(--ink);
}
.layout__link:hover { background: var(--hover); }
.layout__link.is-active { background: var(--active); font-weight: 600; }
.layout__body { flex: 1; min-width: 0; display: flex; flex-direction: column; }
.layout__top {
  display: flex; justify-content: space-between; align-items: center; height: 52px; padding: 0 var(--page-pad-x);
  border-bottom: 1px solid var(--line); background: var(--paper);
}
.layout__user { display: flex; align-items: center; gap: 8px; }
.layout__name { font-weight: 600; }
.layout__main { flex: 1; min-width: 0; padding: 24px var(--page-pad-x) 48px; }
</style>
