import Vue from 'vue'
import Vuex from 'vuex'
import { api } from '@/api'
import { setTokenGetter } from '@/api/http'
import { can } from '@/config/roles'
import { META_FALLBACK } from '@/config/plans'
import { normalizeMeta } from '@/utils/meta'
import { saveSession, clearSession, loadSession } from '@/utils/session'

Vue.use(Vuex)

const restored = loadSession()

const store = new Vuex.Store({
  state: {
    token: restored ? restored.token : '',
    expiresAt: restored ? restored.expires_at : 0,
    admin: restored ? restored.admin : null,
    meta: normalizeMeta(null, META_FALLBACK),
    pendingRequests: 0
  },
  getters: {
    loggedIn: s => !!s.token,
    role: s => (s.admin ? s.admin.role : ''),
    planOptions: s => s.meta.plans,
    featureOptions: s => s.meta.featureOptions,
    featurePattern: s => s.meta.featurePattern,
    devMax: s => s.meta.devMax
  },
  mutations: {
    SET_SESSION(state, s) {
      state.token = s ? s.token : ''
      state.expiresAt = s ? s.expires_at : 0
      state.admin = s ? s.admin : null
      if (!s) state.pendingRequests = 0
    },
    SET_META(state, m) { state.meta = m },
    SET_PENDING(state, n) { state.pendingRequests = n }
  },
  actions: {
    async login({ commit }, { username, password }) {
      const res = await api.auth.login(username, password)
      const session = { token: res.token, expires_at: res.expires_at, admin: res.admin }
      saveSession(session)
      commit('SET_SESSION', session)
      return res.admin
    },
    /** 套餐白名单和功能点规则以服务端为准；取不到时保留兜底常量 */
    async loadMeta({ commit }) {
      try {
        commit('SET_META', normalizeMeta(await api.meta.get(), META_FALLBACK))
      } catch (e) { /* 回退到 config/plans.js */ }
    },
    /** 菜单上申请单的待处理数量角标 */
    async refreshPending({ commit, getters }) {
      if (!can(getters.role, 'request.manage')) return
      try {
        const res = await api.requests.list({ status: 'pending', page: 1, page_size: 1 }, { silent: true })
        commit('SET_PENDING', res.total || 0)
      } catch (e) { /* 角标拿不到不影响使用 */ }
    },
    logout({ commit }) {
      clearSession()
      commit('SET_SESSION', null)
    }
  }
})

setTokenGetter(() => store.state.token)

export default store
