/**
 * 当前作品：作品信息、角色/场景/道具数量、剧集列表、当前剧集。
 * ProjectLayout 进入作品时 load()，侧栏和作品内各页从这里读，不各自重复请求。
 */
import { api } from '@/api'

const LAST_PROJECT_KEY = 'dongai:lastProject'

function emptyState() {
  return {
    current: null,
    loading: false,
    counts: { characters: 0, scenes: 0, props: 0, scripts: 0 },
    episodes: [],
    episodeId: ''
  }
}

function lengthOf(res) {
  if (Array.isArray(res)) return res.length
  if (res && Array.isArray(res.data)) return res.data.length
  return 0
}

export default {
  namespaced: true,
  state: emptyState,
  getters: {
    projectId: state => (state.current ? state.current.id : ''),
    currentEpisode: state => state.episodes.find(e => e.id === state.episodeId) || null
  },
  mutations: {
    SET_PROJECT(state, project) { state.current = project },
    SET_LOADING(state, v) { state.loading = v },
    SET_COUNTS(state, counts) { state.counts = { ...state.counts, ...counts } },
    SET_EPISODES(state, list) { state.episodes = list },
    SET_EPISODE(state, id) { state.episodeId = id || '' },
    SET_EPISODE_NOVEL(state, { id, novel_content }) {
      const ep = state.episodes.find(e => e.id === id)
      if (ep) ep.novel_content = novel_content
    },
    RESET(state) { Object.assign(state, emptyState()) }
  },
  actions: {
    /** 进入作品：作品、数量、剧集并行加载 */
    async load({ commit, dispatch, state }, projectId) {
      if (state.current && state.current.id !== projectId) commit('RESET')
      commit('SET_LOADING', true)
      try {
        const [project] = await Promise.all([
          api.project.get(projectId),
          dispatch('refreshCounts', { projectId }),
          dispatch('refreshEpisodes', projectId)
        ])
        commit('SET_PROJECT', project)
        try { localStorage.setItem(LAST_PROJECT_KEY, projectId) } catch (e) { /* 隐私模式 */ }
        return project
      } finally {
        commit('SET_LOADING', false)
      }
    },
    async refreshCounts({ commit, getters }, payload = {}) {
      const { projectId, setId } = payload
      const pid = projectId || getters.projectId
      if (!pid) return
      const setAtStart = getters.episodeId
      const [characters, scenes, props, scripts] = await Promise.all([
        api.character.list(pid).catch(() => []),
        api.scene.list(pid).catch(() => []),
        api.prop.list(pid).catch(() => []),
        api.script.list(pid, setId).catch(() => null)
      ])
      const patch = {
        characters: lengthOf(characters),
        scenes: lengthOf(scenes),
        props: lengthOf(props)
      }
      // 剧本按集：等待期间若已切到别的集，旧请求的场次不覆盖当前集数量
      if (getters.episodeId === setAtStart) {
        patch.scripts = ((scripts && scripts.data && scripts.data.scripts) || []).length
      }
      commit('SET_COUNTS', patch)
    },
    async refreshEpisodes({ commit, getters }, projectId) {
      const pid = projectId || getters.projectId
      if (!pid) return []
      const list = await api.videoSet.list(pid).catch(() => [])
      commit('SET_EPISODES', Array.isArray(list) ? list : [])
      return list
    },
    setEpisode({ commit }, id) { commit('SET_EPISODE', id) },
    reset({ commit }) { commit('RESET') }
  }
}

/** 上次进入的作品 id（首页“接着做”用） */
export function lastProjectId() {
  try { return localStorage.getItem(LAST_PROJECT_KEY) || '' } catch (e) { return '' }
}
