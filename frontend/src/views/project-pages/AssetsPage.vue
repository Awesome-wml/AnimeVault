<template>
  <ProjectPage :title="conf.label" :subtitle="subtitle">
    <template #actions>
      <BaseButton v-if="conf.hasVoice" variant="text" :loading="assigning" @click="autoAssignVoice">AI 自动配音色</BaseButton>
      <BaseButton variant="text" @click="openForm(null)">手动添加</BaseButton>
      <MoreMenu v-if="items.length" :items="batchMenu" label="批量生成的更多操作" @command="regenerateAll" />
      <BaseButton :variant="items.length ? 'secondary' : 'primary'" @click="showExtract = true">AI 提取{{ conf.label }}</BaseButton>
      <BaseButton v-if="items.length" variant="primary" :loading="running" @click="generateMissing">
        {{ running ? progressText(batch) : `生成全部${conf.imageName}` }}
      </BaseButton>
    </template>

    <BatchProgress :task.sync="batch" :done-text="`${conf.imageName}已生成`" unit="张" :title="`批量生成${conf.imageName}进度`" />

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
 * “生成全部参考图/三视图”逐张串行出图（utils/batchRun），每张完成立即换上卡片的图；
 * 只改图片不影响侧栏数量，所以批量出图不刷新 store。离开页面时 BatchProgress 自动取消剩余。
 */
import { mapState } from 'vuex'
import { api, STYLE_LIBRARY } from '@/api'
import { confirmAction, confirmDelete } from '@/utils/dialogs'
import { runAction, toastError, toastInfo, toastWarning } from '@/utils/notify'
import { batchRun, progressText, isRunning } from '@/utils/batchRun'
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
      batch: null,
      assigning: false,
      showForm: false,
      showExtract: false,
      editing: null
    }
  },
  computed: {
    ...mapState('project', { project: 'current' }),
    conf() { return assetKind(this.kind) },
    running() { return isRunning(this.batch) },
    batchMenu() {
      return [{ command: 'regenerate', label: `全部重新生成${this.conf.imageName}`, disabled: this.running }]
    },
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
    progressText,
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
    /** 生成一张并立即换上卡片的图（单张、批量共用） */
    async requestImage(item) {
      this.generatingId = item.id
      try {
        const res = await api.asset.generate({ asset_type: this.kind, asset_id: item.id, style: (this.project && this.project.style) || '' })
        const path = res && res.data && res.data.img_path
        // 批量期间列表可能被重新加载过（增删、上传），按 id 找当前卡片
        if (path) this.$set(this.items.find(i => i.id === item.id) || item, 'image_path', path)
        return res
      } finally {
        if (this.generatingId === item.id) this.generatingId = ''
      }
    },
    async generate(item) {
      if (this.running) { toastWarning('正在批量生成，请稍候'); return }
      if (this.generatingId) { toastWarning('正在生成另一张图，请稍候'); return }
      await runAction(() => this.requestImage(item), {
        success: `${item.name} 的${this.conf.imageName}已生成`,
        error: `${this.conf.generateText}失败`
      })
    },
    startBatch(list) {
      this.batch = batchRun(list, item => this.requestImage(item), { label: item => item.name })
    },
    /** 主按钮：只处理还没有图的 */
    generateMissing() {
      if (this.running) return
      if (this.generatingId) { toastWarning('正在生成另一张图，请稍候'); return }
      const todo = this.items.filter(i => !i.image_path)
      if (!todo.length) {
        toastInfo(`每个${this.conf.label}都已有${this.conf.imageName}；要重画请在“更多”里选“全部重新生成”`)
        return
      }
      this.startBatch(todo)
    },
    /** 更多 → 全部重新生成：已有的图会被替换，先确认 */
    async regenerateAll() {
      if (this.running || !this.items.length) return
      if (this.generatingId) { toastWarning('正在生成另一张图，请稍候'); return }
      const n = this.items.length
      const msg = `为全部 ${n} ${this.conf.unit}${this.conf.label}重新生成${this.conf.imageName}？已有的图会被替换。`
      if (!(await confirmAction(msg, `全部重新生成${this.conf.imageName}`, '重新生成'))) return
      this.startBatch(this.items.slice())
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
