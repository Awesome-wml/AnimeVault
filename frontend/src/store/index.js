import Vue from 'vue'
import Vuex from 'vuex'
import project from './modules/project'

Vue.use(Vuex)

export default new Vuex.Store({
  modules: { project },

  state: {
    user: null,
    localSession: false, // 授权模式：没有账号登录/退出
    currentProject: null,
    hasApiKey: false
  },
  
  mutations: {
    SET_USER(state, user) {
      state.user = user
    },
    
    SET_LOCAL_SESSION(state, v) {
      state.localSession = !!v
    },

    SET_CURRENT_PROJECT(state, project) {
      state.currentProject = project
    },
    
    SET_HAS_API_KEY(state, hasKey) {
      state.hasApiKey = hasKey
    },
    
    LOGOUT(state) {
      state.user = null
      state.currentProject = null
      state.hasApiKey = false
      localStorage.removeItem('token')
    }
  },
  
  actions: {
    setUser({ commit }, user) {
      commit('SET_USER', user)
    },
    
    setCurrentProject({ commit }, project) {
      commit('SET_CURRENT_PROJECT', project)
    },
    
    setHasApiKey({ commit }, hasKey) {
      commit('SET_HAS_API_KEY', hasKey)
    },
    
    logout({ commit }) {
      commit('LOGOUT')
      commit('project/RESET')
    }
  },
  
  getters: {
    isLoggedIn: state => !!state.user,
    currentProject: state => state.currentProject,
    hasApiKey: state => state.hasApiKey
  }
})
