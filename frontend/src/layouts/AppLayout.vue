<template>
  <div class="app-layout">
    <SideNav :groups="groups || defaultGroups" :brand="groups ? '' : 'DongAI'" :label="navLabel">
      <template v-if="$scopedSlots.head || $slots.head" #head><slot name="head"></slot></template>
      <template v-for="name in groupSlotNames" #[name]><slot :name="name"></slot></template>
      <template #footer>
        <slot name="footer">
          <div v-if="!localSession" class="app-layout__user">
            <span class="app-layout__username" :title="username">{{ username }}</span>
            <button type="button" class="app-layout__logout" @click="logout">退出</button>
          </div>
        </slot>
      </template>
    </SideNav>
    <main class="app-layout__main">
      <router-view :key="$route.path" class="page-in"></router-view>
    </main>
  </div>
</template>

<script>
/**
 * 工作台外壳：左侧 SideNav + 右侧内容区（子路由）。
 * 直接作为路由组件时显示全局菜单；ProjectLayout 传入作品菜单与插槽复用它。
 */
import SideNav from './SideNav.vue'
import { GLOBAL_NAV } from './nav'
import { api } from '@/api'

export default {
  name: 'AppLayout',
  components: { SideNav },
  props: {
    groups: { type: Array, default: null },
    navLabel: { type: String, default: '主菜单' }
  },
  data() {
    return { defaultGroups: GLOBAL_NAV }
  },
  computed: {
    groupSlotNames() {
      return (this.groups || []).filter(g => g.slot).map(g => g.slot)
    },
    localSession() {
      return this.$store.state.localSession
    },
    username() {
      const u = this.$store.state.user
      return (u && u.username) || ''
    }
  },
  created() {
    if (!this.$store.state.user && !this.localSession) {
      api.auth.getMe()
        .then(res => this.$store.dispatch('setUser', (res && res.data) || res))
        .catch(() => {})
    }
  },
  methods: {
    logout() {
      this.$store.dispatch('logout')
      this.$router.push('/login')
    }
  }
}
</script>

<style scoped>
.app-layout {
  min-height: 100vh;
  display: flex;
  flex-wrap: wrap;
  align-items: stretch;
  background: var(--paper);
}
.app-layout__main {
  flex: 1 1 560px;
  min-width: 0;
  padding: var(--page-pad-y) var(--page-pad-x);
}
.app-layout__user {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  min-height: 36px;
  padding: 0 10px;
  font-size: var(--fs-small);
  color: var(--ink-muted);
}
.app-layout__username { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.app-layout__logout {
  flex: none;
  border: 0;
  background: transparent;
  padding: 0;
  color: var(--ink-muted);
  font-size: var(--fs-small);
}
.app-layout__logout:hover { color: var(--ink); }
@media (max-width: 760px) {
  .app-layout__main { flex-basis: 100%; padding: 20px 16px; }
  .app-layout__user { padding: 0; gap: 12px; }
}
</style>
