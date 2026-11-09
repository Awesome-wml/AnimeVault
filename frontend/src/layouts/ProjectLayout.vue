<template>
  <AppLayout :groups="groups" nav-label="作品菜单">
    <template #head>
      <router-link to="/works" class="project-layout__back">‹ 全部作品</router-link>
      <div class="side-nav__name">{{ project ? project.name : '\u00a0' }}</div>
    </template>

    <template #episode>
      <label v-if="episodes.length" class="project-layout__episode">
        <span class="sr-only">当前剧集</span>
        <el-select :value="episodeId" size="small" placeholder="选择剧集" @change="selectEpisode">
          <el-option v-for="ep in episodes" :key="ep.id" :label="ep.name" :value="ep.id"></el-option>
        </el-select>
      </label>
      <router-link v-else :to="`/projects/${pid}/episodes`" class="project-layout__no-episode">还没有剧集，去新建</router-link>
    </template>

    <template #footer>
      <router-link to="/settings/models" class="project-layout__settings">设置</router-link>
    </template>
  </AppLayout>
</template>

<script>
/**
 * 作品内布局：作品侧栏（故事 / 资产〔数量〕/ 制作〔剧集选择器〕）+ 内容区。
 * 作品、数量、剧集都来自 store 的 project 模块；当前剧集与地址栏 ?ep= 同步。
 */
import { mapState } from 'vuex'
import AppLayout from './AppLayout.vue'
import { projectNav } from './nav'

// 这些页面按剧集工作，缺 ?ep 时自动带上第一集
const EPISODE_PAGES = ['shots', 'voice', 'final']

export default {
  name: 'ProjectLayout',
  components: { AppLayout },
  computed: {
    ...mapState('project', { project: 'current', counts: 'counts', episodes: 'episodes', episodeId: 'episodeId' }),
    pid() { return this.$route.params.pid },
    groups() { return projectNav(this.pid, this.counts, this.episodeId) },
    pageKey() { return this.$route.path.split('/').pop() }
  },
  watch: {
    pid: { immediate: true, handler: 'loadProject' },
    '$route.query.ep'() { this.syncEpisode() },
    episodes() { this.syncEpisode() },
    pageKey() { this.syncEpisode() }
  },
  methods: {
    async loadProject(pid) {
      if (!pid) return
      try {
        await this.$store.dispatch('project/load', pid)
      } catch (e) {
        // 作品不存在或无权访问：回到全部作品（错误提示由请求拦截器给出）
        this.$router.replace('/works').catch(() => {})
        return
      }
      this.syncEpisode()
    },
    syncEpisode() {
      const q = this.$route.query.ep
      const exists = id => this.episodes.some(e => e.id === id)
      if (q && exists(q)) {
        this.$store.dispatch('project/setEpisode', q)
        return
      }
      const fallback = exists(this.episodeId) ? this.episodeId : (this.episodes[0] ? this.episodes[0].id : '')
      this.$store.dispatch('project/setEpisode', fallback)
      if (fallback && EPISODE_PAGES.includes(this.pageKey) && q !== fallback) {
        this.$router.replace({ path: this.$route.path, query: { ...this.$route.query, ep: fallback } }).catch(() => {})
      }
    },
    selectEpisode(id) {
      this.$store.dispatch('project/setEpisode', id)
      if (EPISODE_PAGES.includes(this.pageKey)) {
        this.$router.replace({ path: this.$route.path, query: { ...this.$route.query, ep: id } }).catch(() => {})
      }
    }
  }
}
</script>

<style scoped>
.project-layout__back {
  display: flex;
  align-items: center;
  min-height: 32px;
  padding: 0 10px;
  font-size: var(--fs-small);
  color: var(--ink-muted);
}
.project-layout__back:hover { color: var(--ink); }
.project-layout__episode { display: block; padding: 2px 10px 4px; }
.project-layout__episode >>> .el-select { width: 100%; }
.project-layout__episode >>> .el-input__inner { background: transparent; height: 34px; line-height: 34px; padding-left: 8px; }
.project-layout__no-episode {
  display: block;
  padding: 2px 10px 6px;
  font-size: var(--fs-small);
  color: var(--ink-muted);
  text-decoration: underline;
  text-underline-offset: 4px;
}
.project-layout__settings {
  display: flex;
  align-items: center;
  min-height: 36px;
  padding: 0 10px;
  border-radius: var(--radius-nav);
  color: var(--ink);
}
.project-layout__settings:hover { background: var(--hover); }
@media (max-width: 760px) {
  .project-layout__episode { flex: 0 0 100%; padding: 2px 0 4px; }
}
</style>
