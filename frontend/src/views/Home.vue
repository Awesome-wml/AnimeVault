<template>
  <div class="page" v-loading="loading">
    <template v-if="last">
      <PageHeader :subtitle="lastSummary">
        <template #title>接着做《{{ last.name }}》</template>
        <template #actions>
          <BaseButton variant="text" @click="showNew = true">新建作品</BaseButton>
          <BaseButton variant="primary" :to="continueTo">继续</BaseButton>
        </template>
      </PageHeader>

      <div class="split">
        <div class="split__main">
          <MediaFrame :src="cover.src" :label="cover.label" :tone="2" controls />
        </div>
        <section class="split__side home__todo" aria-labelledby="todo-title">
          <h2 id="todo-title" class="section-title home__todo-title">需要你处理</h2>
          <router-link v-for="item in todos" :key="item.key" :to="item.to" class="list-row">
            <span>{{ item.text }}</span>
            <StatusText :status="item.alert ? 'action_alert' : 'action'" :text="item.action" />
          </router-link>
          <EmptyState v-if="detailLoaded && !todos.length" compact title="眼下没有要处理的事。" />
        </section>
      </div>
    </template>

    <template v-else-if="!loading">
      <PageHeader title="开始第一部作品" subtitle="贴一篇小说，或者让 AI 先写一篇。">
        <template #actions>
          <BaseButton variant="primary" @click="showNew = true">新建作品</BaseButton>
        </template>
      </PageHeader>
      <EmptyState seal="戏" title="还没有作品" description="新建作品后，角色、场景、道具和分镜会从小说里自动整理出来。" />
    </template>

    <section v-if="recent.length" class="section">
      <div class="section__head">
        <h2 class="section-title">最近的作品</h2>
        <BaseButton variant="text" to="/works" class="home__all">全部作品</BaseButton>
      </div>
      <div class="card-grid card-grid--sm">
        <AssetCard
          v-for="p in recent"
          :key="p.id"
          :title="p.name"
          :meta="metaOf(p)"
          :tone="p.id"
          placeholder="封面"
          :to="entryOf(p)"
        />
      </div>
    </section>

    <NewProjectDialog :visible.sync="showNew" />
  </div>
</template>

<script>
/**
 * 工作首页：接着上次的作品 + 需要你处理 + 最近作品。
 * 所有数字都来自接口：上次作品 = 最近进入过的作品（本机记录），没有记录则取最新创建的。
 * 后端暂不提供分镜审核/失败状态，所以“需要你处理”只列能算出来的：没视频的镜头、缺参考图的资产、未配置模型密钥。
 */
import { api } from '@/api'
import { lastProjectId } from '@/store/modules/project'
import NewProjectDialog from '@/components/project/NewProjectDialog.vue'
import { projectMeta, projectEntry, createdAt } from '@/components/project/meta'

const ASSET_KINDS = [
  { key: 'character', label: '角色', page: 'characters', list: pid => api.character.list(pid) },
  { key: 'scene', label: '场景', page: 'scenes', list: pid => api.scene.list(pid) },
  { key: 'prop', label: '道具', page: 'props', list: pid => api.prop.list(pid) }
]

const asList = res => (Array.isArray(res) ? res : (res && Array.isArray(res.data) ? res.data : []))

export default {
  name: 'HomePage',
  components: { NewProjectDialog },
  data() {
    return {
      loading: true,
      detailLoaded: false,
      showNew: false,
      projects: [],
      last: null,
      shots: [],
      assets: {},
      episodes: [],
      needsKey: false
    }
  },
  computed: {
    recent() {
      return this.projects.filter(p => !this.last || p.id !== this.last.id).slice(0, 4)
    },
    continueTo() {
      return this.last ? projectEntry(this.last) : '/works'
    },
    withVideo() {
      return this.shots.filter(s => s.video_path)
    },
    lastSummary() {
      if (!this.last || !this.detailLoaded) return ''
      const n = this.shots.length
      if (n) {
        const ep = this.episodes.length ? `${this.episodes.length} 集，` : ''
        return `${ep}共 ${n} 个镜头，${this.withVideo.length} 个已出视频。`
      }
      return this.last.novel_content ? '小说已经写好，下一步拆分镜。' : '还没有小说，先写一篇或贴进来。'
    },
    cover() {
      const shot = this.withVideo[this.withVideo.length - 1]
      if (shot) return { src: api.staticUrl(shot.video_path), label: '' }
      return { src: '', label: this.shots.length ? `${this.shots.length} 个镜头 · 还没有视频` : '还没有画面' }
    },
    todos() {
      if (!this.last) return []
      const pid = this.last.id
      const items = []
      const noVideo = this.shots.length - this.withVideo.length
      if (noVideo > 0) {
        const first = this.shots.find(s => !s.video_path)
        items.push({
          key: 'shots',
          text: noVideo === 1 ? `镜头 ${first.shot_no} 还没有视频` : `${noVideo} 个镜头还没有视频`,
          action: '去生成',
          to: `/projects/${pid}/shots`
        })
      }
      ASSET_KINDS.forEach(kind => {
        const missing = (this.assets[kind.key] || []).filter(a => !a.image_path && !a.img_path)
        if (!missing.length) return
        items.push({
          key: kind.key,
          text: missing.length === 1 ? `${kind.label}“${missing[0].name}”缺参考图` : `${missing.length} 个${kind.label}缺参考图`,
          action: '生成',
          to: `/projects/${pid}/${kind.page}`
        })
      })
      if (this.needsKey) {
        items.push({ key: 'key', text: '还没有配置模型密钥', action: '去设置', to: '/settings/models' })
      }
      return items
    }
  },
  async created() {
    try {
      const list = asList(await api.project.list())
      this.projects = list.slice().sort((a, b) => createdAt(b) - createdAt(a))
      const lastId = lastProjectId()
      this.last = this.projects.find(p => p.id === lastId) || this.projects[0] || null
    } catch (e) {
      this.projects = []
    } finally {
      this.loading = false
    }
    if (this.last) this.loadDetail(this.last.id)
  },
  methods: {
    metaOf: projectMeta,
    entryOf: projectEntry,
    async loadDetail(pid) {
      const safe = p => p.catch(() => null)
      const [shots, episodes, config, models, ...assetLists] = await Promise.all([
        safe(api.shot.list(pid)),
        safe(api.videoSet.list(pid)),
        safe(api.auth.getConfig()),
        safe(api.model.list()),
        ...ASSET_KINDS.map(k => safe(k.list(pid)))
      ])
      this.shots = asList(shots)
      this.episodes = asList(episodes)
      const assets = {}
      ASSET_KINDS.forEach((k, i) => { assets[k.key] = asList(assetLists[i]) })
      this.assets = assets
      const hasGlobalKey = !!(config && config.data && config.data.has_api_key)
      const hasPresetKey = asList(models).some(m => (m.api_keys && m.api_keys.some(Boolean)) || m.api_key)
      this.needsKey = !!config && !!models && !hasGlobalKey && !hasPresetKey
      this.detailLoaded = true
    }
  }
}
</script>

<style scoped>
.home__todo { display: flex; flex-direction: column; gap: 4px; }
.home__todo-title { margin-bottom: 6px; }
.home__all { min-height: 44px; font-size: var(--fs-body); }
</style>
