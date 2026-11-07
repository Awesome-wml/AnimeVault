import Vue from 'vue'
import Vuex from 'vuex'

Vue.use(Vuex)

export default new Vuex.Store({
  state: {
    user: null,
    currentProject: null,
    hasApiKey: false
  },
  
  mutations: {
    SET_USER(state, user) {
      state.user = user
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
    }
  },
  
  getters: {
    isLoggedIn: state => !!state.user,
    currentProject: state => state.currentProject,
    hasApiKey: state => state.hasApiKey
  }
})
