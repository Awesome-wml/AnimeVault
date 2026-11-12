<template>
  <ProjectPage title="小说" :subtitle="subtitle">
    <template #actions>
      <BaseButton variant="text" :loading="saving" :disabled="!dirty" @click="save">保存</BaseButton>
      <BaseButton variant="primary" :to="`/projects/${pid}/script`">转剧本</BaseButton>
    </template>

    <div class="split">
      <div class="split__main form-stack">
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
          :set-id="episodeId"
          :prompts="prompts.novel"
          :model-groups="modelGroups"
          :default-model="defaultModel"
          :default-genre="project ? project.genre || '' : ''"
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
 * 小说：正文编辑 + 润色 + AI 写小说。
 * 资产提取和拆分镜统一放到剧本页：小说页只负责保存正文并进入转剧本。
 */
import { mapState, mapGetters } from 'vuex'
import { api } from '@/api'
import { confirmAction } from '@/utils/dialogs'
import { runAction, toastError } from '@/utils/notify'
import { loadModelOptions, loadPrompts } from '@/components/novel/options'
import PolishPanel from '@/components/novel/PolishPanel.vue'
import PolishDialog from '@/components/novel/PolishDialog.vue'
import NovelWriter from '@/components/novel/NovelWriter.vue'
import ProjectPage from './ProjectPage.vue'

export default {
  name: 'NovelPage',
  components: { ProjectPage, PolishPanel, PolishDialog, NovelWriter },
  props: { pid: { type: String, required: true }, ep: { type: String, default: '' } },
  data() {
    return {
      content: '',
      saved: '',
      loaded: false,
      saving: false,
      writing: false,
      modelGroups: [],
      defaultModel: '',
      prompts: { extract: [], split: [], novel: [], polish: [] },
      polish: { visible: false, text: '', sourceLength: 0 }
    }
  },
  computed: {
    ...mapState('project', { project: 'current' }),
    ...mapGetters('project', { episode: 'currentEpisode' }),
    episodeId() { return this.ep || (this.episode ? this.episode.id : '') },
    /** 换了集（或这一集刚加载出来）才重新取正文；同一集的列表刷新不能覆盖正在写/改的内容 */
    episodeKey() { return `${this.episodeId}|${this.episode ? this.episode.id : ''}` },
    dirty() { return this.loaded && this.content !== this.saved },
    subtitle() {
      if (!this.loaded) return ''
      const n = this.content.length.toLocaleString()
      return `${this.dirty ? '有未保存的修改' : '已保存'} · ${n} 字`
    }
  },
  watch: {
    project: { immediate: true, handler: 'init' },
    episodeKey() { this.loadNovel(true) }
  },
  async beforeRouteLeave(to, from, next) {
    if (!this.dirty) return next()
    next(await confirmAction('小说有未保存的修改，离开后会丢失。', '离开小说页', '离开'))
  },
  methods: {
    async init(project) {
      if (!project) return
      this.loadNovel()
      if (this.loaded) return
      this.loaded = true
      try {
        const [models, prompts] = await Promise.all([loadModelOptions(), loadPrompts(project.genre || '')])
        this.modelGroups = models.groups
        this.defaultModel = models.chatDefaultKey || models.defaultKey
        this.prompts = prompts
      } catch (e) {
        toastError(e, '模型或提示词列表加载失败')
      }
    },
    /** 作品对象刷新（保存、侧栏计数等）不能冲掉正在写或没保存的正文；换集才强制重取 */
    loadNovel(force = false) {
      if (!force && (this.writing || this.dirty)) return
      this.content = this.saved = (this.episode && this.episode.novel_content) || ''
    },
    async save() {
      if (!this.dirty) return true
      this.saving = true
      const text = this.content
      const ok = await runAction(() => api.novel.save(this.pid, this.episodeId, text), { success: '已保存', error: '保存失败' })
      this.saving = false
      if (ok) {
        this.saved = text
        this.$store.commit('project/SET_EPISODE_NOVEL', { id: this.episodeId, novel_content: text })
      }
      return !!ok
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
