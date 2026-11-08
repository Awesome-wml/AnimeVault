<template>
  <ProjectPage :title="conf.label" :subtitle="subtitle">
    <template #actions>
      <BaseButton v-if="conf.hasVoice" variant="text" :loading="assigning" @click="autoAssignVoice">AI 自动配音色</BaseButton>
      <BaseButton variant="text" @click="openForm(null)">手动添加</BaseButton>
      <BaseButton variant="primary" @click="showExtract = true">AI 提取{{ conf.label }}</BaseButton>
    </template>

    <div v-loading="loading" class="card-grid" :class="conf.gridClass">
      <AssetItem
        v-for="item in items"
        :key="item.id"
        :kind="kind"
        :item="item"
        :voices="voices"
        :busy="generatingId === item.id"
        @generate="generate"
        @upload="pickFile"
        @edit="openForm"
        @delete="remove"
        @voice="changeVoice"
      />
    </div>

    <EmptyState
      v-if="!loading && !items.length"
      :title="`还没有${conf.label}`"
      :description="`点右上角“AI 提取${conf.label}”，从小说里自动整理；也可以手动添加。`"
    />

    <AssetFormDialog :visible.sync="showForm" :kind="kind" :project-id="pid" :item="editing" :voices="voices" @saved="reload" />
    <ExtractDialog
      :visible.sync="showExtract"
      :kind="kind"
      :project-id="pid"
      :novel="project ? project.novel_content || '' : ''"
      :style-id="style ? style.id : ''"
      :style-name="style ? style.name : ''"
      @done="reload"
    />
    <FilePicker ref="picker" accept="image/*" @select="upload" />
  </ProjectPage>
</template>

<script>
/**
 * 角色 / 场景 / 道具页（路由传 kind）。一个页面只显示一类；项目风格在 /style 页设置。
 * 增删、提取后刷新本页列表和侧栏数量（store project/refreshCounts）。
 */
import { mapState } from 'vuex'
import { api, STYLE_LIBRARY } from '@/api'
import { confirmDelete } from '@/utils/dialogs'
import { runAction, toastError, toastWarning } from '@/utils/notify'
import { assetKind } from '@/components/asset/kinds'
import { loadVoices } from '@/components/voice/voices'
import AssetItem from '@/components/asset/AssetItem.vue'
import AssetFormDialog from '@/components/asset/AssetFormDialog.vue'
import ExtractDialog from '@/components/asset/ExtractDialog.vue'
import ProjectPage from './ProjectPage.vue'

export default {
  name: 'AssetsPage',
  components: { ProjectPage, AssetItem, AssetFormDialog, ExtractDialog },
  props: {
    pid: { type: String, required: true },
    ep: { type: String, default: '' },
    kind: { type: String, required: true }
  },
  data() {
    return {
      loading: false,
      items: [],
      voices: [],
      generatingId: '',
      assigning: false,
      showForm: false,
      showExtract: false,
      editing: null
    }
  },
  computed: {
    ...mapState('project', { project: 'current' }),
    conf() { return assetKind(this.kind) },
    subtitle() { return this.loading && !this.items.length ? '' : `${this.items.length} ${this.conf.unit}${this.conf.label}` },
    style() {
      const id = this.project && this.project.style
      return STYLE_LIBRARY.find(s => s.id === id) || null
    }
  },
  created() {
    this.load()
    if (this.conf.hasVoice) {
      loadVoices().then(v => { this.voices = v }, e => toastError(e, '音色列表加载失败'))
    }
  },
  methods: {
    async load() {
      this.loading = true
      try {
        const list = await this.conf.api.list(this.pid)
        this.items = Array.isArray(list) ? list : []
      } catch (e) {
        toastError(e, `${this.conf.label}列表加载失败`)
      } finally {
        this.loading = false
      }
    },
    /** 列表和侧栏数量一起刷新 */
    reload() {
      this.$store.dispatch('project/refreshCounts', this.pid)
      return this.load()
    },
    openForm(item) {
      this.editing = item
      this.showForm = true
    },
    async generate(item) {
      if (this.generatingId) { toastWarning('正在生成另一张图，请稍候'); return }
      this.generatingId = item.id
      const ok = await runAction(
        () => api.asset.generate({ asset_type: this.kind, asset_id: item.id, style: (this.project && this.project.style) || '' }),
        { success: `${item.name} 的${this.conf.imageName}已生成`, error: `${this.conf.generateText}失败` }
      )
      this.generatingId = ''
      if (ok) this.load()
    },
    pickFile(item) {
      this.$refs.picker.open(item)
    },
    async upload(file, item) {
      const ok = await runAction(() => api.asset.upload(this.kind, item.id, file), {
        success: res => (res && res.message) || '已上传',
        error: '上传失败'
      })
      if (ok) this.load()
    },
    async remove(item) {
      if (!(await confirmDelete(`删除${this.conf.label}“${item.name}”？`))) return
      const ok = await runAction(() => this.conf.api.delete(item.id), { success: '已删除', error: '删除失败' })
      if (ok) this.reload()
    },
    async changeVoice(item, voiceName) {
      const prev = item.voice_name
      item.voice_name = voiceName
      const ok = await runAction(() => api.character.update(item.id, { voice_name: voiceName }), {
        success: `${item.name} 的音色已更新`,
        error: '音色更新失败'
      })
      if (!ok) item.voice_name = prev
    },
    async autoAssignVoice() {
      this.assigning = true
      const ok = await runAction(() => api.tts.autoAssign(this.pid), {
        success: res => (res && res.message) || '已自动配好音色',
        error: '自动配音色失败'
      })
      this.assigning = false
      if (ok) this.load()
    }
  }
}
</script>
