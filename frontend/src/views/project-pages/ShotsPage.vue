<template>
  <ProjectPage title="分镜" :subtitle="subtitle">
    <template #actions>
      <BaseButton variant="text" :loading="splitting" @click="split">拆分镜</BaseButton>
      <MoreMenu :items="imageMenu" label="生成画面的更多操作" @command="onMenu" />
      <BaseButton v-if="shots.length" :loading="imageRunning" @click="generateMissingImages">
        {{ imageRunning ? progressText(imageBatch) : '生成全部画面' }}
      </BaseButton>
      <BaseButton variant="primary" :disabled="!shots.length" @click="showBatch = true">批量生成视频</BaseButton>
    </template>

    <BatchProgress :task.sync="imageBatch" done-text="画面已生成" unit="张" title="批量生成画面进度" />

    <div v-if="shots.length" class="master-detail">
      <ShotList v-model="selectedId" :shots="shots" :progress="progress" />
      <div class="master-detail__detail">
        <ShotDetail
          v-if="selected"
          :shot="selected"
          :characters="characters"
          :model-name="modelName"
          :progress="progress[selected.shot_no] || null"
          :video-busy="!!busy['video:' + selected.id]"
          :image-busy="!!busy['image:' + selected.id]"
          @save="save"
          @generate-video="generateVideo"
          @generate-image="generateImage"
          @manual-video="openManual"
          @delete="remove"
        />
      </div>
    </div>

    <EmptyState v-else-if="!loading" title="这一集还没有分镜" description="在剧本页点“一键提取”，或点右上角“拆分镜”，按剧本场次拆成镜头。">
      <template #actions>
        <BaseButton :to="`/projects/${pid}/script`">去剧本页</BaseButton>
      </template>
    </EmptyState>

    <BatchGenerateDialog :visible.sync="showBatch" :project-id="pid" :total="shots.length" :pending="pendingCount" @done="reload" />
    <ManualVideoDialog :visible.sync="showManual" :shot="manualShot" @done="reload" />
    <ImageGenDialog v-model="imageGen" :visible.sync="showImageGen" :groups="imageModelGroups" />
  </ProjectPage>
</template>

<script>
/**
 * 分镜页：按当前剧集（?ep= / store 当前剧集）列出镜头，右侧编辑选中镜头。
 * 视频生成进度通过 SSE（/api/video/events/:pid）实时更新。
 * “生成全部画面”逐张串行出图（utils/batchRun），每张完成立即换上缩略图；换剧集或离开页面时取消剩余。
 */
import { mapState, mapGetters } from 'vuex'
import { api } from '@/api'
import { confirmAction, confirmDelete } from '@/utils/dialogs'
import { runAction, toastError, toastSuccess, toastWarning } from '@/utils/notify'
import { batchRun, progressText, isRunning } from '@/utils/batchRun'
import ShotList from '@/components/shot/ShotList.vue'
import ShotDetail from '@/components/shot/ShotDetail.vue'
import BatchGenerateDialog from '@/components/shot/BatchGenerateDialog.vue'
import ManualVideoDialog from '@/components/shot/ManualVideoDialog.vue'
import ImageGenDialog from '@/components/image/ImageGenDialog.vue'
import { readImageGen, saveImageGen, imageGenPayload, modelLabel } from '@/components/image/imageGen'
import { loadModelOptions } from '@/components/novel/options'
import { loadVideoModels, findModel } from '@/components/project/videoModels'
import { isSegment, shotTitle, splitMessage } from '@/components/shot/segment'
import ProjectPage from './ProjectPage.vue'

export default {
  name: 'ShotsPage',
  components: { ProjectPage, ShotList, ShotDetail, BatchGenerateDialog, ManualVideoDialog, ImageGenDialog },
  props: { pid: { type: String, required: true }, ep: { type: String, default: '' } },
  data() {
    return {
      loading: false,
      splitting: false,
      shots: [],
      characters: [],
      selectedId: '',
      progress: {},
      busy: {},
      imageBatch: null,
      showBatch: false,
      showManual: false,
      manualShot: null,
      videoModels: [],
      // 出图设置（文生图模型），与资产页共用同一份本地记录
      imageGen: readImageGen(this.pid),
      showImageGen: false,
      imageModelGroups: []
    }
  },
  computed: {
    ...mapState('project', { project: 'current', scriptCount: state => state.counts.scripts || 0 }),
    ...mapGetters('project', { episode: 'currentEpisode' }),
    episodeId() { return this.ep || (this.episode ? this.episode.id : '') },
    selected() { return this.shots.find(s => s.id === this.selectedId) || null },
    imageRunning() { return isRunning(this.imageBatch) },
    imageMenu() {
      const menu = [{ command: 'image-settings', label: '出图设置…' }]
      if (this.shots.length) menu.push({ command: 'regenerate', label: '全部重新生成画面', disabled: this.imageRunning })
      return menu
    },
    pendingCount() { return this.shots.filter(s => !s.video_path).length },
    modelName() {
      const m = findModel(this.videoModels, this.project && this.project.video_model)
      return m ? m.name : 'Seedance 2.0 Fast'
    },
    subtitle() {
      const parts = []
      if (this.episode) parts.push(this.episode.name)
      if (this.shots.length) {
        const segs = this.shots.filter(isSegment).length
        parts.push(segs === this.shots.length ? `${segs} 段（每段一次视频生成）` : `${this.shots.length} 个镜头`)
        parts.push(`已出视频 ${this.shots.length - this.pendingCount} 个`)
      }
      if (this.videoModels.length) parts.push(this.modelName)
      return parts.join(' · ')
    }
  },
  watch: {
    episodeId: { immediate: true, handler: 'onEpisode' },
    imageGen(v) { saveImageGen(this.pid, v) }
  },
  created() {
    api.character.list(this.pid).then(list => { this.characters = Array.isArray(list) ? list : [] }, e => toastError(e, '角色列表加载失败'))
    loadVideoModels().then(v => { this.videoModels = v }, e => toastError(e, '视频模型列表加载失败'))
    loadModelOptions('image').then(m => {
      this.imageModelGroups = m.groups
      if (this.imageGen.model && !modelLabel(m.groups, this.imageGen.model)) this.imageGen = { ...this.imageGen, model: '' }
    }, e => toastError(e, '文生图模型列表加载失败'))
    this.connectEvents()
  },
  beforeDestroy() {
    if (this.events) this.events.close()
  },
  methods: {
    progressText,
    /** 换剧集：上一集的批量出图停掉，再加载新一集 */
    onEpisode() {
      if (this.imageBatch) this.imageBatch.cancel()
      this.imageBatch = null
      this.load()
    },
    async load() {
      // 只采用最后一次请求的结果：保存后的刷新还没回来时又生成了画面，旧结果不能把新画面盖掉
      const seq = this.loadSeq = (this.loadSeq || 0) + 1
      this.loading = true
      try {
        const list = await api.shot.list(this.pid, this.episodeId)
        if (seq !== this.loadSeq) return
        this.shots = Array.isArray(list) ? list : []
        if (!this.selected) this.selectedId = this.shots[0] ? this.shots[0].id : ''
      } catch (e) {
        toastError(e, '分镜加载失败')
      } finally {
        this.loading = false
      }
    },
    /** 列表 + 侧栏剧集镜头数一起刷新 */
    reload() {
      this.$store.dispatch('project/refreshEpisodes', this.pid)
      return this.load()
    },
    connectEvents() {
      this.events = new EventSource(api.video.eventsUrl(this.pid))
      this.events.onmessage = e => {
        let data
        try { data = JSON.parse(e.data) } catch (err) { console.warn('无法解析的进度消息', e.data); return }
        this.$set(this.progress, data.shot_no, { step: data.step, progress: data.progress, msg: data.msg })
        if (data.step === 'done') {
          toastSuccess(`镜头 ${data.shot_no} 生成完成`)
          this.load()
        }
      }
    },
    setBusy(key, v) { this.$set(this.busy, key, v) },
    onMenu(cmd) {
      if (cmd === 'image-settings') this.showImageGen = true
      else if (cmd === 'regenerate') this.regenerateAllImages()
    },
    /** 保存字段；改逐句台词时后端会重新校正起止秒并回填，完整提示词预览也要重新拉 */
    async save(shot, fields) {
      const res = await runAction(() => api.shot.update(shot.id, fields), { error: '保存失败' })
      if (!res) return
      Object.assign(shot, fields, (res && res.data) || {})
      if (res.message && res.message.startsWith('已保存，但')) toastWarning(res.message)
      if (isSegment(shot)) this.load()
    },
    async split() {
      const novel = (this.project && this.project.novel_content) || ''
      if (!novel.trim() && !this.scriptCount) { toastWarning('小说还是空的，先去小说页贴入内容'); return }
      const where = this.episode ? `“${this.episode.name}”` : '当前剧集'
      const source = this.scriptCount ? `按剧本（${this.scriptCount} 场）` : '按小说全文'
      if (!(await confirmAction(`${source}拆分镜，新镜头会追加到${where}。`, '拆分镜', '开始拆分'))) return
      this.splitting = true
      const res = await runAction(
        () => api.shot.split({ project_id: this.pid, novel_paragraph: novel, video_set_id: this.episodeId }),
        { success: splitMessage, error: '拆分镜失败' }
      )
      this.splitting = false
      if (res) this.reload()
    },
    async generateVideo(shot) {
      const len = isSegment(shot) ? `（${shot.duration} 秒，${this.modelName}）` : ''
      if (!(await confirmAction(`为${shotTitle(shot)}生成视频${len}？会打开豆包自动化浏览器。`, '生成视频', '生成'))) return
      const key = 'video:' + shot.id
      this.setBusy(key, true)
      const ok = await runAction(() => api.video.generateSingle(shot.id, null), {
        success: res => (res && res.message) || '视频已生成',
        error: '生成视频失败'
      })
      this.setBusy(key, false)
      if (ok) this.reload()
    },
    /** 生成一张画面并立即换上（单张、批量共用） */
    async requestImage(shot) {
      const key = 'image:' + shot.id
      this.setBusy(key, true)
      try {
        const res = await api.image.generate({
          shot_id: shot.id, prompt: shot.prompt, neg_prompt: shot.neg_prompt, ...imageGenPayload(this.imageGen)
        })
        const path = res && res.data && res.data.img_path
        // 期间列表可能被 SSE 刷新过，按 id 找当前镜头
        if (path) {
          this.$set(this.shots.find(s => s.id === shot.id) || shot, 'img_path', path)
          // 还在路上的列表刷新是生成前读的库，作废它（画面已换上，参考图列表下次刷新时更新）
          this.loadSeq = (this.loadSeq || 0) + 1
          this.loading = false
        }
        return res
      } finally {
        this.setBusy(key, false)
      }
    },
    async generateImage(shot) {
      if (!shot.prompt) { toastWarning('先在“提示词与生成参数”里填写画面提示词'); return }
      if (this.imageRunning) { toastWarning('正在批量生成画面，请稍候'); return }
      await runAction(() => this.requestImage(shot), { success: '画面已生成', error: '生成画面失败' })
    },
    /** 批量出图；没有画面提示词的镜头跳过 */
    startImageBatch(list) {
      const todo = list.filter(s => s.prompt)
      const skipped = list.length - todo.length
      if (skipped) toastWarning(`${skipped} 个镜头没有画面提示词，已跳过`)
      if (!todo.length) return
      this.imageBatch = batchRun(todo, shot => this.requestImage(shot), { label: shotTitle })
    },
    /** 次按钮：只处理还没有画面的镜头 */
    generateMissingImages() {
      if (this.imageRunning) return
      const todo = this.shots.filter(s => !s.img_path)
      if (!todo.length) { toastWarning('每个镜头都已有画面；要重画请在“更多”里选“全部重新生成画面”'); return }
      this.startImageBatch(todo)
    },
    /** 更多 → 全部重新生成画面：已有画面会被替换，先确认 */
    async regenerateAllImages() {
      if (this.imageRunning || !this.shots.length) return
      const msg = `为这一集全部 ${this.shots.length} 个镜头重新生成画面？已有的画面会被替换。`
      if (!(await confirmAction(msg, '全部重新生成画面', '重新生成'))) return
      this.startImageBatch(this.shots.slice())
    },
    openManual(shot) {
      this.manualShot = shot
      this.showManual = true
    },
    async remove(shot) {
      if (!(await confirmDelete(`删除${shotTitle(shot)}？`))) return
      const ok = await runAction(() => api.shot.delete(shot.id), { success: '已删除', error: '删除失败' })
      if (!ok) return
      const i = this.shots.indexOf(shot)
      const next = this.shots[i + 1] || this.shots[i - 1]
      this.selectedId = next ? next.id : ''
      this.reload()
    }
  }
}
</script>
