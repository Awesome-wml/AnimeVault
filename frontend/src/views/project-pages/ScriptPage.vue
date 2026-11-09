<template>
  <ProjectPage title="剧本" :subtitle="subtitle">
    <template #actions>
      <BaseButton variant="text" :loading="adding" :disabled="converting" @click="addScene">新增一场</BaseButton>
      <BaseButton variant="text" :loading="converting" @click="convert">{{ scenes.length ? '重新转剧本' : '转剧本' }}</BaseButton>
      <BaseButton variant="text" :loading="splitting" :disabled="busy && !splitting" @click="splitOnly">拆分镜</BaseButton>
      <BaseButton variant="primary" :loading="extracting" :disabled="busy && !extracting" @click="extractAll">一键提取</BaseButton>
    </template>

    <div class="split">
      <div class="split__main form-stack">
        <ExtractProgress :progress="progress" @close="progress = null" />
        <div v-loading="loading" class="script-list">
          <SceneCard
            v-for="sc in scenes"
            :key="sc.id"
            :ref="`scene-${sc.id}`"
            :scene="sc"
            :characters="characterNames"
            :saving="savingId === sc.id"
            @save="saveScene"
            @delete="removeScene"
          />
        </div>
        <EmptyState
          v-if="!loading && !scenes.length"
          title="还没有剧本"
          description="点右上角“转剧本”，把小说润色并拆成分场剧本（地点、出场角色、动作、台词）。有剧本后，在本页提取角色/道具/场景并拆分镜。"
        >
          <template v-if="!novel.trim()" #actions>
            <BaseButton :to="`/projects/${pid}/novel`">先去小说页贴入小说</BaseButton>
          </template>
        </EmptyState>
      </div>

      <aside class="split__side form-stack">
        <ScriptSettings
          v-model="settings"
          :model-groups="modelGroups"
          :prompts="prompts.script"
          :project="project"
          :saving="savingSettings"
          @save-project="saveProjectSettings"
        />
        <ExtractSettings
          v-model="extractSettings"
          :model-groups="modelGroups"
          :prompts="prompts"
          :episode-name="episode ? episode.name : ''"
        />
        <section class="section">
          <p class="note">按小说正文（{{ novelLength }} 字）生成，长文自动分块转换；重新转剧本会覆盖现有场次和你做过的修改。</p>
          <p class="note">“一键提取”按剧本场次依次生成角色、道具、场景，再拆成分镜；“拆分镜”只重新生成分镜。</p>
        </section>
      </aside>
    </div>
  </ProjectPage>
</template>

<script>
/**
 * 剧本：小说 → 分场剧本（SSE 推接收字数与第几块）、场次列表、逐场编辑。
 * 资产三合一提取与拆分镜入口也放在本页：先转剧本，再一键提取 / 拆分镜。
 * 叙事人称、目标时长存在作品里（ScriptSettings），转剧本时一并传给后端。
 */
import { mapState, mapGetters } from 'vuex'
import { api } from '@/api'
import { confirmAction, confirmDelete } from '@/utils/dialogs'
import { runAction, toastError, toastInfo, toastSuccess, toastWarning } from '@/utils/notify'
import { loadModelOptions, loadPrompts, parseModelKey } from '@/components/novel/options'
import ExtractSettings from '@/components/novel/ExtractSettings.vue'
import ExtractProgress from '@/components/novel/ExtractProgress.vue'
import { extractTask, failTask, finishTask, withSplitProgress } from '@/components/novel/splitProgress'
import { splitMessage } from '@/components/shot/segment'
import SceneCard from '@/components/script/SceneCard.vue'
import ScriptSettings from '@/components/script/ScriptSettings.vue'
import { sceneTitle } from '@/components/script/scene'
import ProjectPage from './ProjectPage.vue'

export default {
  name: 'ScriptPage',
  components: { ProjectPage, ScriptSettings, ExtractSettings, ExtractProgress, SceneCard },
  props: { pid: { type: String, required: true }, ep: { type: String, default: '' } },
  data() {
    return {
      loading: false,
      converting: false,
      adding: false,
      extracting: false,
      splitting: false,
      savingId: '',
      savingSettings: false,
      scenes: [],
      characterNames: [],
      modelGroups: [],
      prompts: {},
      settings: { model: '', prompt: '' },
      extractSettings: { extractModel: '', extractPrompt: '', splitModel: '', splitPrompt: '' },
      progress: null,
      optionsLoaded: false
    }
  },
  computed: {
    ...mapState('project', { project: 'current' }),
    ...mapGetters('project', { episode: 'currentEpisode' }),
    novel() { return (this.project && this.project.novel_content) || '' },
    novelLength() { return this.novel.length.toLocaleString() },
    busy() { return this.converting || this.adding || this.extracting || this.splitting },
    episodeId() { return this.ep || (this.episode ? this.episode.id : '') },
    subtitle() {
      if (this.loading && !this.scenes.length) return ''
      if (!this.scenes.length) return '小说 → 分场剧本 → 资产 / 分镜'
      const lines = this.scenes.reduce((n, s) => n + (s.dialogues || []).length, 0)
      return `${this.scenes.length} 场 · ${lines} 句台词与旁白`
    }
  },
  watch: {
    project: { immediate: true, handler: 'loadOptions' }
  },
  created() {
    this.load()
    api.character.list(this.pid).then(
      list => { this.characterNames = (Array.isArray(list) ? list : []).map(c => c.name).filter(Boolean) },
      e => toastError(e, '角色列表加载失败')
    )
  },
  methods: {
    async load() {
      this.loading = true
      try {
        const res = await api.script.list(this.pid)
        this.scenes = (res && res.data && res.data.scripts) || []
      } catch (e) {
        toastError(e, '剧本加载失败')
      } finally {
        this.loading = false
      }
    },
    async loadOptions(project) {
      if (!project || this.optionsLoaded) return
      this.optionsLoaded = true
      try {
        const [models, prompts] = await Promise.all([loadModelOptions('chat'), loadPrompts(project.genre || '')])
        this.modelGroups = models.groups
        this.settings = { ...this.settings, model: models.defaultKey }
        this.extractSettings = { ...this.extractSettings, extractModel: models.defaultKey, splitModel: models.defaultKey }
        this.prompts = prompts
      } catch (e) {
        toastError(e, '模型或提示词列表加载失败')
      }
    },
    refreshSide() {
      this.$store.dispatch('project/refreshCounts', this.pid)
      this.$store.dispatch('project/refreshEpisodes', this.pid)
    },
    splitParams() {
      return {
        project_id: this.pid,
        novel_paragraph: this.novel,
        ...parseModelKey(this.extractSettings.splitModel),
        prompt_id: this.extractSettings.splitPrompt,
        video_set_id: this.episodeId
      }
    },
    /** 提取前：至少要有小说正文或已有剧本场次 */
    ready() {
      if (!this.scenes.length && !this.novel.trim()) {
        toastWarning('请先在小说页贴入正文并转剧本')
        return false
      }
      return true
    },
    async extractAll() {
      if (!(await this.ready())) return
      this.extracting = true
      const task = this.progress = extractTask('assets')
      try {
        toastInfo(this.scenes.length ? `正在按剧本（${this.scenes.length} 场）提取角色、道具、场景…` : '正在提取角色、道具、场景…')
        await api.asset.extractAll({
          project_id: this.pid,
          novel_text: this.novel,
          ...parseModelKey(this.extractSettings.extractModel),
          prompt_id: this.extractSettings.extractPrompt
        }, chars => { task.chars = chars })
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
    async convert() {
      if (!this.novel.trim()) { toastWarning('小说还是空的，先去小说页贴入内容'); return }
      if (this.scenes.length &&
          !(await confirmAction(`重新转剧本会覆盖现有 ${this.scenes.length} 场（包括你做过的修改）。`, '重新转剧本', '覆盖并转换'))) return
      this.converting = true
      const task = this.progress = extractTask('script')
      try {
        const res = await api.script.convert({
          project_id: this.pid,
          novel_text: this.novel,
          ...parseModelKey(this.settings.model),
          prompt_id: this.settings.prompt,
          person: (this.project && this.project.script_person) || undefined,
          target_seconds: (this.project && this.project.script_target_seconds) || 0
        }, (chars, chunk, total) => { task.chars = chars; task.chunk = chunk; task.total = total })
        finishTask(task, res.message || '剧本转换完成')
        toastSuccess(res.message || '剧本转换完成')
        await this.load()
        this.refreshSide()
      } catch (e) {
        failTask(task, e, '转剧本失败')
        toastError(e, '转剧本失败')
      } finally {
        this.converting = false
      }
    },
    /** 叙事人称 / 目标时长存到作品（下次转剧本沿用） */
    async saveProjectSettings(fields) {
      this.savingSettings = true
      const ok = await runAction(() => api.project.update(this.pid, fields), { success: '转剧本设置已保存', error: '保存失败' })
      this.savingSettings = false
      if (!ok) return
      const merged = { ...this.project, ...fields }
      if ('script_target_seconds' in fields) merged.script_target_seconds = fields.script_target_seconds || null
      this.$store.commit('project/SET_PROJECT', merged)
    },
    async saveScene(scene, fields) {
      this.savingId = scene.id
      const ok = await runAction(() => api.script.update(scene.id, fields), { success: `${sceneTitle({ ...scene, ...fields })} 已保存`, error: '保存失败' })
      this.savingId = ''
      if (!ok) return
      Object.assign(scene, fields)
      const card = this.$refs[`scene-${scene.id}`]
      ;(Array.isArray(card) ? card[0] : card).close()
    },
    async removeScene(scene) {
      if (!(await confirmDelete(`删除${sceneTitle(scene)}？`))) return
      const ok = await runAction(() => api.script.delete(scene.id), { success: '已删除', error: '删除失败' })
      if (!ok) return
      this.scenes = this.scenes.filter(s => s.id !== scene.id)
      this.refreshSide()
    },
    async addScene() {
      this.adding = true
      const res = await runAction(() => api.script.create({ project_id: this.pid, location: '新场景' }), { error: '新增失败' })
      this.adding = false
      if (!res) return
      await this.load()
      this.refreshSide()
      this.$nextTick(() => {
        const card = this.$refs[`scene-${res.data.id}`]
        const el = Array.isArray(card) ? card[0] : card
        if (el) { el.startEdit(); el.$el.scrollIntoView({ block: 'center' }) }
      })
    }
  }
}
</script>

<style scoped>
.script-list { display: flex; flex-direction: column; min-height: 40px; }
</style>
