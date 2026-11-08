<template>
  <ProjectPage title="剧本" :subtitle="subtitle">
    <template #actions>
      <BaseButton variant="text" :loading="adding" :disabled="converting" @click="addScene">新增一场</BaseButton>
      <BaseButton variant="primary" :loading="converting" @click="convert">{{ scenes.length ? '重新转剧本' : '转剧本' }}</BaseButton>
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
          description="点右上角“转剧本”，把小说润色并拆成分场剧本（地点、出场角色、动作、台词）。有剧本后，一键提取和拆分镜都按剧本场次来。"
        >
          <template v-if="!novel.trim()" #actions>
            <BaseButton :to="`/projects/${pid}/novel`">先去小说页贴入小说</BaseButton>
          </template>
        </EmptyState>
      </div>

      <aside class="split__side form-stack">
        <section class="section">
          <h2 class="section-title">转剧本设置</h2>
          <FormField label="模型">
            <ModelSelect v-model="settings.model" :groups="modelGroups" />
          </FormField>
          <FormField label="提示词">
            <PromptSelect v-model="settings.prompt" :prompts="prompts" />
          </FormField>
          <p class="note">按小说正文（{{ novelLength }} 字）生成；重新转剧本会覆盖现有场次和你做过的修改。</p>
          <p class="note">有剧本时，小说页“一键提取”的资产提取和拆分镜都基于剧本场次；删掉全部场次则回到按小说提取。</p>
        </section>
      </aside>
    </div>
  </ProjectPage>
</template>

<script>
/**
 * 剧本：小说 → 分场剧本（SSE 推接收字数）、场次列表、逐场编辑（地点、时间、出场角色、动作、台词逐条增删改）。
 * 场次数显示在侧栏“剧本”旁（store project/refreshCounts）。
 */
import { mapState } from 'vuex'
import { api } from '@/api'
import { confirmAction, confirmDelete } from '@/utils/dialogs'
import { runAction, toastError, toastSuccess, toastWarning } from '@/utils/notify'
import { loadModelOptions, loadPrompts, parseModelKey } from '@/components/novel/options'
import ModelSelect from '@/components/novel/ModelSelect.vue'
import PromptSelect from '@/components/novel/PromptSelect.vue'
import ExtractProgress from '@/components/novel/ExtractProgress.vue'
import { extractTask, failTask, finishTask } from '@/components/novel/splitProgress'
import SceneCard from '@/components/script/SceneCard.vue'
import { sceneTitle } from '@/components/script/scene'
import ProjectPage from './ProjectPage.vue'

export default {
  name: 'ScriptPage',
  components: { ProjectPage, ModelSelect, PromptSelect, ExtractProgress, SceneCard },
  props: { pid: { type: String, required: true }, ep: { type: String, default: '' } },
  data() {
    return {
      loading: false,
      converting: false,
      adding: false,
      savingId: '',
      scenes: [],
      characterNames: [],
      modelGroups: [],
      prompts: [],
      settings: { model: '', prompt: '' },
      progress: null,
      optionsLoaded: false
    }
  },
  computed: {
    ...mapState('project', { project: 'current' }),
    novel() { return (this.project && this.project.novel_content) || '' },
    novelLength() { return this.novel.length.toLocaleString() },
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
        this.prompts = prompts.script
      } catch (e) {
        toastError(e, '模型或提示词列表加载失败')
      }
    },
    refreshSide() {
      this.$store.dispatch('project/refreshCounts', this.pid)
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
          prompt_id: this.settings.prompt
        }, chars => { task.chars = chars })
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
