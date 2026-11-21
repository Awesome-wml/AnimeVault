<template>
  <ProjectPage :title="conf.label" :subtitle="subtitle">
    <template #actions>
      <BaseButton v-if="kind === 'character'" variant="text" :loading="designing" :disabled="!items.length" @click="designVoices">AI 设计音色</BaseButton>
      <BaseButton v-else-if="conf.hasVoice" variant="text" :loading="assigning" @click="autoAssignVoice">AI 自动配音色</BaseButton>
      <BaseButton variant="text" @click="openForm(null)">手动添加</BaseButton>
      <MoreMenu :items="batchMenu" label="批量生成的更多操作" @command="onMenu" />
      <BaseButton :variant="items.length ? 'secondary' : 'primary'" @click="showExtract = true">AI 提取{{ conf.label }}</BaseButton>
      <BaseButton v-if="items.length" variant="primary" :loading="running" @click="generateMissing">
        {{ running ? progressText(batch) : `生成全部${conf.imageName}` }}
      </BaseButton>
    </template>

    <BatchProgress :task.sync="batch" :done-text="`${conf.imageName}已生成`" unit="张" :title="`批量生成${conf.imageName}进度`" />

    <!-- 角色：旁白的声音与撞音色提示 -->
    <div v-if="kind === 'character' && items.length" class="voice-bar">
      <span class="voice-bar__label">旁白的声音</span>
      <el-input v-model.trim="narrator" size="small" class="voice-bar__input" maxlength="30" placeholder="如：沉稳青年男声" @keyup.enter.native="saveNarrator" />
      <BaseButton variant="text" :loading="savingNarrator" :disabled="narrator === savedNarrator" @click="saveNarrator">保存</BaseButton>
      <span class="note">全片旁白同一个人；角色的声音在各自卡片里改。</span>
    </div>
    <p v-for="w in voiceWarnings" :key="w" class="note note--warn voice-warn">{{ w }}</p>

    <!-- 角色：大图卡片网格 -->
    <div v-if="kind === 'character'" v-loading="loading" class="card-grid card-grid--asset-portrait">
      <CharacterCard
        v-for="item in items"
        :key="item.id"
        :item="item"
        :voices="voices"
        :busy="generatingId === item.id"
        :saving-forms="savingFormsId === item.id"
        :has-ref="!!refFiles[item.id]"
        @generate="generate"
        @upload="pickFile"
        @pick-ref="pickRef"
        @clear-ref="clearRef"
        @edit="openForm"
        @delete="remove"
        @voice="changeVoice"
        @save-forms="saveForms"
        @change-outfit="openOutfit"
      />
    </div>

    <!-- 场景 / 道具：卡片网格 -->
    <div v-else v-loading="loading" class="card-grid" :class="conf.gridClass">
      <AssetItem
        v-for="item in items"
        :key="item.id"
        :kind="kind"
        :item="item"
        :voices="voices"
        :busy="generatingId === item.id"
        :saving-forms="savingFormsId === item.id"
        :has-ref="!!refFiles[item.id]"
        @generate="generate"
        @upload="pickFile"
        @pick-ref="pickRef"
        @clear-ref="clearRef"
        @edit="openForm"
        @delete="remove"
        @voice="changeVoice"
        @save-forms="saveForms"
      />
    </div>

    <EmptyState
      v-if="!loading && !items.length"
      :title="`还没有${conf.label}`"
      :description="`点右上角“AI 提取${conf.label}”，从小说里自动整理；也可以手动添加。`"
    />

    <AssetFormDialog :visible.sync="showForm" :kind="kind" :project-id="pid" :item="editing" :voices="voices" @saved="reload" />
    <OutfitDialog :visible.sync="showOutfit" :item="outfitTarget" :saving="savingOutfit" @submit="submitOutfit" />
    <ExtractDialog
      :visible.sync="showExtract"
      :kind="kind"
      :project-id="pid"
      :novel="episode ? episode.novel_content || '' : ''"
      :medium="styleFields.medium"
      :genre="styleFields.genre"
      :style-name="styleName"
      @done="reload"
    />
    <ImageGenDialog
      v-model="imageGen"
      :visible.sync="showImageGen"
      :groups="imageModelGroups"
      :default-label="imageDefaultLabel"
      :sheet-prompts="sheetPrompts"
      :show-sheet-prompt="kind === 'character'"
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
 * “更多 → 出图设置”选文生图模型（与角色三视图提示词），单张、批量出图都用它。
 * 角色按形态出图：一个形态一张三视图（components/asset/forms.js 的 formJobs 展开待办），
 * 卡片上的形态标签可切换显示哪张图、改形态名和场次（saveForms 走 api.character.update）。
 * 场景同理按视角出图（components/asset/views.js 的 viewJobs），视角标签改名 / 机位走 api.scene.update。
 */
import { mapState, mapGetters } from 'vuex'
import { api } from '@/api'
import { confirmAction, confirmDelete } from '@/utils/dialogs'
import { runAction, toastError, toastInfo, toastWarning } from '@/utils/notify'
import { batchRun, progressText, isRunning } from '@/utils/batchRun'
import { assetKind } from '@/components/asset/kinds'
import { formJobs, characterForms, cleanForms } from '@/components/asset/forms'
import { viewJobs, sceneViews } from '@/components/asset/views'
import { loadVoices } from '@/components/voice/voices'
import { loadStyleLibrary } from '@/components/project/styleLoader'
import { EMPTY_LIBRARY, styleFields, styleLabel } from '@/components/project/styleLibrary'
import AssetItem from '@/components/asset/AssetItem.vue'
import CharacterCard from '@/components/asset/CharacterCard.vue'
import OutfitDialog from '@/components/asset/OutfitDialog.vue'
import AssetFormDialog from '@/components/asset/AssetFormDialog.vue'
import ExtractDialog from '@/components/asset/ExtractDialog.vue'
import ImageGenDialog from '@/components/image/ImageGenDialog.vue'
import { readImageGen, saveImageGen, imageGenPayload, modelLabel } from '@/components/image/imageGen'
import { loadModelOptions, loadPrompts } from '@/components/novel/options'
import ProjectPage from './ProjectPage.vue'

export default {
  name: 'AssetsPage',
  components: { ProjectPage, AssetItem, CharacterCard, OutfitDialog, AssetFormDialog, ExtractDialog, ImageGenDialog },
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
      savingFormsId: '',
      batch: null,
      assigning: false,
      designing: false,
      narrator: '',
      savingNarrator: false,
      voiceWarnings: [],
      showForm: false,
      showExtract: false,
      editing: null,
      // 出图设置（文生图模型 / 三视图提示词），按作品记在本地
      imageGen: readImageGen(this.pid),
      showImageGen: false,
      imageModelGroups: [],
      imageDefaultLabel: '',
      sheetPrompts: [],
      styleLib: EMPTY_LIBRARY,
      // 本次出图可选参考图：item.id → File（一次性，不持久化）
      refFiles: {},
      // 变装（新增穿搭形态）弹窗
      outfitTarget: null,
      showOutfit: false,
      savingOutfit: false
    }
  },
  computed: {
    ...mapState('project', { project: 'current' }),
    ...mapGetters('project', { episode: 'currentEpisode' }),
    conf() { return assetKind(this.kind) },
    running() { return isRunning(this.batch) },
    batchMenu() {
      const menu = [{ command: 'image-settings', label: '出图设置…' }]
      if (this.items.length) menu.push({ command: 'regenerate', label: `全部重新生成${this.conf.imageName}`, disabled: this.running })
      return menu
    },
    imageModelName() { return modelLabel(this.imageModelGroups, this.imageGen.model) },
    subtitle() {
      if (this.loading && !this.items.length) return ''
      const parts = [`${this.items.length} ${this.conf.unit}${this.conf.label}`]
      if (this.imageModelName) parts.push(`出图：${this.imageModelName}`)
      return parts.join(' · ')
    },
    /** 作品当前的媒介 + 题材（提取、出图都带上；旧 style 字段自动映射） */
    savedNarrator() { return (this.project && this.project.narrator_voice) || '' },
    styleFields() { return styleFields(this.styleLib, this.project) },
    styleName() { return styleLabel(this.styleLib, this.project) }
  },
  watch: {
    imageGen(v) { saveImageGen(this.pid, v) },
    savedNarrator: { immediate: true, handler(v) { this.narrator = v } }
  },
  created() {
    this.load()
    this.loadImageOptions()
    loadStyleLibrary().then(lib => { this.styleLib = lib }, e => toastError(e, '风格库加载失败'))
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
    async loadImageOptions() {
      try {
        const genre = (this.project && this.project.genre) || ''
        const [models, prompts] = await Promise.all([loadModelOptions(), loadPrompts(genre)])
        this.imageModelGroups = models.imageGroups
        this.imageDefaultLabel = models.imageDefaultLabel
        this.sheetPrompts = prompts.sheet
        // 记住的模型已被删掉：回到默认
        if (this.imageGen.model && !this.imageModelName) this.imageGen = { ...this.imageGen, model: '' }
      } catch (e) {
        toastError(e, '文生图模型列表加载失败')
      }
    },
    onMenu(cmd) {
      if (cmd === 'image-settings') this.showImageGen = true
      else if (cmd === 'regenerate') this.regenerateAll()
    },
    /** 列表和侧栏数量一起刷新 */
    reload() {
      this.$store.dispatch('project/refreshCounts', { projectId: this.pid })
      return this.load()
    },
    openForm(item) {
      this.editing = item
      this.showForm = true
    },
    /** 把一张新图写进卡片：角色写到对应形态（第一形态同步 image_path），其他直接改 image_path。
     *  批量期间列表可能被重新加载过（增删、上传），按 id 找当前卡片 */
    applyImage(item, formIndex, path) {
      const target = this.items.find(i => i.id === item.id) || item
      if (this.kind === 'prop') { this.$set(target, 'image_path', path); return }
      const key = this.kind === 'scene' ? 'views' : 'forms'
      const list = (this.kind === 'scene' ? sceneViews : characterForms)(target)
      this.$set(target, key, list.map((f, i) => (i === formIndex ? { ...f, image_path: path } : f)))
      if (formIndex === 0) this.$set(target, 'image_path', path)
    },
    /** 生成一张并立即换上卡片的图（单张、批量共用）；formIndex 只对角色有意义；可选参考图跟随本次生成 */
    async requestImage(item, formIndex = 0) {
      this.generatingId = item.id
      let refPath = ''
      try {
        const refFile = this.refFiles[item.id]
        if (refFile) {
          const up = await api.asset.refUpload(refFile)
          refPath = (up && up.data && up.data.ref_path) || ''
        }
        const res = await api.asset.generate({
          asset_type: this.kind,
          asset_id: item.id,
          ...this.styleFields,
          ...(this.kind === 'character' ? { form_index: formIndex } : {}),
          ...(this.kind === 'scene' ? { view_index: formIndex } : {}),
          ...(refPath ? { ref_image: refPath } : {}),
          ...imageGenPayload(this.imageGen, this.kind === 'character')
        })
        const path = res && res.data && res.data.img_path
        if (path) this.applyImage(item, formIndex, path)
        return res
      } finally {
        this.$delete(this.refFiles, item.id)
        if (this.generatingId === item.id) this.generatingId = ''
      }
    },
    async generate(item, formIndex = 0) {
      if (this.running) { toastWarning('正在批量生成，请稍候'); return }
      if (this.generatingId) { toastWarning('正在生成另一张图，请稍候'); return }
      await runAction(() => this.requestImage(item, formIndex), {
        success: `${item.name} 的${this.conf.imageName}已生成`,
        error: `${this.conf.generateText}失败`
      })
    },
    /** 批量待办：角色按形态展开（一个形态一张），场景 / 道具一项一张 */
    jobs(missingOnly) {
      if (this.kind === 'character') return formJobs(this.items, missingOnly)
      if (this.kind === 'scene') return viewJobs(this.items, missingOnly)
      return this.items.filter(i => !missingOnly || !i.image_path).map(item => ({ item, formIndex: 0, label: item.name }))
    },
    startBatch(list) {
      this.batch = batchRun(list, job => this.requestImage(job.item, job.formIndex), { label: job => job.label })
    },
    /** 主按钮：只处理还没有图的 */
    generateMissing() {
      if (this.running) return
      if (this.generatingId) { toastWarning('正在生成另一张图，请稍候'); return }
      const todo = this.jobs(true)
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
      const todo = this.jobs(false)
      const n = this.items.length
      const count = todo.length > n ? `（${todo.length} 张）` : ''
      const msg = `为全部 ${n} ${this.conf.unit}${this.conf.label}重新生成${this.conf.imageName}${count}？已有的图会被替换。`
      if (!(await confirmAction(msg, `全部重新生成${this.conf.imageName}`, '重新生成'))) return
      this.startBatch(todo)
    },
    pickFile(item, formIndex = 0) {
      this.$refs.picker.open({ item, formIndex, purpose: 'upload' })
    },
    pickRef(item, formIndex = 0) {
      this.$refs.picker.open({ item, formIndex, purpose: 'ref' })
    },
    clearRef(item) {
      this.$delete(this.refFiles, item.id)
    },
    async upload(file, { item, formIndex, purpose }) {
      if (purpose === 'ref') {
        this.$set(this.refFiles, item.id, file)
        return
      }
      const ok = await runAction(() => api.asset.upload(this.kind, item.id, file, this.kind === 'prop' ? undefined : formIndex), {
        success: res => (res && res.message) || '已上传',
        error: '上传失败'
      })
      if (ok) this.load()
    },
    /** 卡片上改形态名 / 场次（角色）或视角名 / 机位（场景）：整份 forms / views 提交，成功后刷新本卡 */
    async saveForms(item, list, done) {
      const isScene = this.kind === 'scene'
      const key = isScene ? 'views' : 'forms'
      this.savingFormsId = item.id
      const ok = await runAction(() => this.conf.api.update(item.id, { [key]: list }), {
        success: `${item.name} 的${isScene ? '视角' : '形态'}已更新`,
        error: `${isScene ? '视角' : '形态'}保存失败`
      })
      this.savingFormsId = ''
      if (ok) {
        this.$set(this.items.find(i => i.id === item.id) || item, key, list)
        if (done) done()
      }
    },
    openOutfit(item) {
      this.outfitTarget = item
      this.showOutfit = true
    },
    /** 变装：给角色追加一套穿搭形态，整份 forms 提交后端 */
    async submitOutfit(draft) {
      const item = this.outfitTarget
      if (!item) return
      const forms = cleanForms([
        ...characterForms(item),
        { name: draft.name, outfit: draft.outfit, scene_nos: draft.scene_nos, image_path: null }
      ])
      this.savingOutfit = true
      const ok = await runAction(() => api.character.update(item.id, { forms }), {
        success: '已新增穿搭形态',
        error: '变装保存失败'
      })
      this.savingOutfit = false
      if (ok) {
        this.$set(this.items.find(i => i.id === item.id) || item, 'forms', forms)
        this.showOutfit = false
      }
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
    /** AI 设计音色：全体角色一起定声音设定；已设计过的问一句要不要重做（手改过的始终不动） */
    async designVoices() {
      const designed = this.items.some(i => i.voice_design_source === 'ai')
      let overwrite = false
      if (designed) {
        overwrite = await confirmAction('已经有 AI 设计过的声音。全部重新设计会换掉它们（手动改过的不动），已出的视频不受影响，之后新出的段会用新声音。', '重新设计音色', '全部重新设计')
        if (!overwrite && !this.items.some(i => !i.voice_design)) return
      }
      this.designing = true
      const res = await runAction(() => api.character.designVoices({ project_id: this.pid, overwrite }), {
        success: r => [r && r.message, r && r.data && r.data.note].filter(Boolean).join('；') || '音色设计完成',
        error: 'AI 设计音色失败'
      })
      this.designing = false
      if (!res) return
      const data = res.data || {}
      this.voiceWarnings = data.warnings || []
      if (data.narrator_voice && this.project) {
        this.$store.commit('project/SET_PROJECT', { ...this.project, narrator_voice: data.narrator_voice })
      }
      this.load()
    },
    async saveNarrator() {
      if (this.narrator === this.savedNarrator) return
      this.savingNarrator = true
      const ok = await runAction(() => api.project.update(this.pid, { narrator_voice: this.narrator }), {
        success: '旁白的声音已保存，之后新出的段会用它', error: '保存失败'
      })
      this.savingNarrator = false
      if (ok) {
        const fresh = await api.project.get(this.pid).catch(() => null)
        if (fresh) this.$store.commit('project/SET_PROJECT', fresh)
      }
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

<style scoped>
.voice-bar { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin-bottom: 12px; }
.voice-bar__label { font-size: var(--fs-small); color: var(--ink); }
.voice-bar__input { width: 220px; }
.voice-warn { margin: 0 0 8px; }
</style>
