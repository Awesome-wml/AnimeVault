<template>
  <ProjectPage title="小说" :subtitle="subtitle">
    <template #actions>
      <BaseButton variant="text" :loading="saving" :disabled="!dirty" @click="save">保存</BaseButton>
      <BaseButton variant="text" :loading="splitting" :disabled="busy && !splitting" @click="splitOnly">只拆分镜</BaseButton>
      <BaseButton variant="primary" :loading="extracting" :disabled="busy && !extracting" @click="extractAll">一键提取</BaseButton>
    </template>

    <div class="split">
      <div class="split__main form-stack">
        <ExtractProgress :progress="progress" @close="progress = null" />
        <el-input
          v-model="content"
          v-loading="writing"
          type="textarea"
          :autosize="{ minRows: 26, maxRows: 60 }"
          placeholder="把小说贴到这里，或展开右侧“AI 写一篇小说”。"
          label="小说内容"
          @keydown.native.meta.s.prevent="save"
          @keydown.native.ctrl.s.prevent="save"
        />
      </div>

      <aside class="split__side form-stack">
        <ExtractSettings v-model="settings" :model-groups="modelGroups" :prompts="prompts" :episode-name="episode ? episode.name : ''" />
        <PolishPanel
          :project-id="pid"
          :text="content"
          :model-groups="modelGroups"
          :default-model="defaultModel"
          :prompts="prompts.polish"
          @result="showPolish"
        />
        <NovelWriter
          :project-id="pid"
          :prompts="prompts.novel"
          :default-style="project ? project.style || '' : ''"
          @start="content = ''; writing = true"
          @chunk="t => (content += t)"
          @finish="writing = false"
        />
      </aside>
    </div>

    <PolishDialog :visible.sync="polish.visible" :text="polish.text" :source-length="polish.sourceLength" @confirm="applyPolish" />
  </ProjectPage>
</template>

<script>
/**
 * 小说：正文编辑 + 一键提取（资产三合一 → 拆分镜）+ 只拆分镜 + 润色 + AI 写小说。
 * 提取后刷新侧栏的角色/场景/道具数量和剧集镜头数。
 */
import { splitMessage } from '@/components/shot/segment'
import { mapState, mapGetters } from 'vuex'
import { api } from '@/api'
import { confirmAction } from '@/utils/dialogs'
import { runAction, toastError, toastInfo, toastSuccess, toastWarning } from '@/utils/notify'
import { loadModelOptions, loadPrompts, parseModelKey } from '@/components/novel/options'
import ExtractSettings from '@/components/novel/ExtractSettings.vue'
import PolishPanel from '@/components/novel/PolishPanel.vue'
import PolishDialog from '@/components/novel/PolishDialog.vue'
import NovelWriter from '@/components/novel/NovelWriter.vue'
import ExtractProgress from '@/components/novel/ExtractProgress.vue'
import { extractTask, failTask, finishTask, withSplitProgress } from '@/components/novel/splitProgress'
import ProjectPage from './ProjectPage.vue'

export default {
  name: 'NovelPage',
  components: { ProjectPage, ExtractSettings, PolishPanel, PolishDialog, NovelWriter, ExtractProgress },
  props: { pid: { type: String, required: true }, ep: { type: String, default: '' } },
  data() {
    return {
      content: '',
      saved: '',
      loaded: false,
      saving: false,
      extracting: false,
      splitting: false,
      writing: false,
      modelGroups: [],
      defaultModel: '',
      prompts: { extract: [], split: [], novel: [], polish: [] },
      settings: { extractModel: '', extractPrompt: '', splitModel: '', splitPrompt: '' },
      polish: { visible: false, text: '', sourceLength: 0 },
      progress: null // 一键提取 / 拆分镜的分阶段进度，见 ExtractProgress
    }
  },
  computed: {
    ...mapState('project', { project: 'current' }),
    ...mapGetters('project', { episode: 'currentEpisode' }),
    dirty() { return this.loaded && this.content !== this.saved },
    busy() { return this.extracting || this.splitting || this.writing },
    subtitle() {
      if (!this.loaded) return ''
      const n = this.content.length.toLocaleString()
      return `${this.dirty ? '有未保存的修改' : '已保存'} · ${n} 字`
    },
    episodeId() { return this.ep || (this.episode ? this.episode.id : '') }
  },
  watch: {
    project: { immediate: true, handler: 'init' }
  },
  async beforeRouteLeave(to, from, next) {
    if (!this.dirty) return next()
    next(await confirmAction('小说有未保存的修改，离开后会丢失。', '离开小说页', '离开'))
  },
  methods: {
    async init(project) {
      if (!project || this.loaded) return
      this.content = this.saved = project.novel_content || ''
      this.loaded = true
      try {
        const [models, prompts] = await Promise.all([loadModelOptions(), loadPrompts(project.genre || '')])
        this.modelGroups = models.groups
        this.defaultModel = models.defaultKey
        this.settings = { ...this.settings, extractModel: models.defaultKey, splitModel: models.defaultKey }
        this.prompts = prompts
      } catch (e) {
        toastError(e, '模型或提示词列表加载失败')
      }
    },
    async save() {
      if (!this.dirty) return true
      this.saving = true
      const text = this.content
      const ok = await runAction(() => api.novel.save(this.pid, text), { success: '已保存', error: '保存失败' })
      this.saving = false
      if (ok) {
        this.saved = text
        this.$store.commit('project/SET_PROJECT', { ...this.project, novel_content: text })
      }
      return !!ok
    },
    splitParams() {
      return {
        project_id: this.pid,
        novel_paragraph: this.content,
        ...parseModelKey(this.settings.splitModel),
        prompt_id: this.settings.splitPrompt,
        video_set_id: this.episodeId
      }
    },
    /** 提取前：正文非空、先保存 */
    async ready() {
      if (!this.content.trim()) { toastWarning('请先贴入小说内容'); return false }
      return this.save()
    },
    async extractAll() {
      if (!(await this.ready())) return
      this.extracting = true
      const task = this.progress = extractTask('assets')
      try {
        toastInfo('正在提取角色、道具、场景…')
        await api.asset.extractAll({
          project_id: this.pid,
          novel_text: this.content,
          ...parseModelKey(this.settings.extractModel),
          prompt_id: this.settings.extractPrompt
        })
        this.refreshSide()
      } catch (e) {
        failTask(task, e, '资产提取失败')
        toastError(e, '一键提取没有全部完成')
        this.extracting = false
        return
      }
      try {
        toastInfo('正在拆分镜…')
        const res = await withSplitProgress(task, this.pid, () => api.shot.split(this.splitParams()))
        finishTask(task, `一键提取完成：已生成角色、道具、场景；${splitMessage(res)}`)
        toastSuccess('一键提取完成：已生成角色、道具、场景和分镜')
      } catch (e) {
        failTask(task, e, '资产已提取，拆分镜失败')
        toastError(e, '一键提取没有全部完成')
      } finally {
        this.extracting = false
        this.refreshSide()
      }
    },
    async splitOnly() {
      if (!(await this.ready())) return
      this.splitting = true
      const task = this.progress = extractTask('shots')
      try {
        const res = await withSplitProgress(task, this.pid, () => api.shot.split(this.splitParams()))
        finishTask(task, splitMessage(res))
        toastSuccess(splitMessage(res))
        this.refreshSide()
      } catch (e) {
        failTask(task, e, '拆分镜失败')
        toastError(e, '拆分镜失败')
      } finally {
        this.splitting = false
      }
    },
    refreshSide() {
      this.$store.dispatch('project/refreshCounts', this.pid)
      this.$store.dispatch('project/refreshEpisodes', this.pid)
    },
    showPolish({ text, sourceLength }) {
      this.polish = { visible: true, text, sourceLength }
    },
    async applyPolish(text) {
      this.content = text
      await this.save()
    }
  }
}
</script>
