import Vue from 'vue'
import Vuex from 'vuex'
import { api } from '@/api'
import { setTokenGetter } from '@/api/http'
import { saveSession, clearSession, loadSession } from '@/utils/session'

Vue.use(Vuex)

const restored = loadSession()

const store = new Vuex.Store({
  state: {
    token: restored ? restored.token : '',
    expiresAt: restored ? restored.expires_at : 0,
    admin: restored ? restored.admin : null
  },
  getters: {
    loggedIn: s => !!s.token,
    role: s => (s.admin ? s.admin.role : '')
  },
  mutations: {
    SET_SESSION(state, s) {
      state.token = s ? s.token : ''
      state.expiresAt = s ? s.expires_at : 0
      state.admin = s ? s.admin : null
    }
  },
  actions: {
    async login({ commit }, { username, password }) {
      const res = await api.auth.login(username, password)
      const session = { token: res.token, expires_at: res.expires_at, admin: res.admin }
      saveSession(session)
      commit('SET_SESSION', session)
      return res.admin
    },
    logout({ commit }) {
      clearSession()
      commit('SET_SESSION', null)
    }
  }
})

setTokenGetter(() => store.state.token)

export default store
