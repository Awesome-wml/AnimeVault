<template>
  <ProjectPage title="风格" subtitle="先选媒介再选题材，贯穿角色、场景、分镜画面，全片保持统一。">
    <template #actions>
      <BaseButton :loading="suggesting" @click="suggest">AI 识别</BaseButton>
      <BaseButton variant="primary" :loading="saving" :disabled="!dirty" @click="save">保存</BaseButton>
    </template>

    <p v-if="suggestion" class="style-ai" role="status">
      AI 推荐：<strong>{{ suggestionText }}</strong>（把握 {{ Math.round(suggestion.confidence * 100) }}%<template v-if="suggestion.source === 'rule'">，按关键词判断</template>）。{{ suggestion.reason }}
      已帮你选中，确认后点右上角保存。
    </p>
    <p v-else-if="project && project.style_source === 'ai' && project.style_reason" class="style-ai" role="status">
      当前风格由 AI 根据小说识别：{{ project.style_reason }}。不合适可以直接改选后保存。
    </p>
    <p v-else-if="project && project.style_source === 'auto'" class="style-ai" role="status">
      这个作品还没识别风格：在小说页贴入正文并保存后会自动识别，也可以点右上角「AI 识别」。
    </p>

    <p v-if="mediumUnset" class="style-alert" role="alert">
      这个作品还没有选择画面类型，已为你默认选中「{{ medium ? medium.name : '真人实拍' }}」；请确认后点右上角保存。
      不保存的话，系统也会按真人实拍出图，但建议显式保存，避免角色、分镜和视频的画风对不上。
    </p>

    <section class="style-step" aria-labelledby="style-medium-title">
      <h2 id="style-medium-title" class="section-title">第一步 · 媒介</h2>
      <StyleChoiceGrid v-model="groupId" :items="lib.medium_groups" label="媒介" ratio="16 / 9" />
      <div v-if="subMediums.length" class="chip-group" role="radiogroup" aria-label="2D 画风">
        <button
          v-for="m in subMediums"
          :key="m.id"
          type="button"
          class="chip"
          role="radio"
          :aria-checked="m.id === mediumId ? 'true' : 'false'"
          :aria-pressed="m.id === mediumId ? 'true' : 'false'"
          :title="m.description"
          @click="mediumId = m.id"
        >{{ m.name }} · {{ m.description }}</button>
      </div>
    </section>

    <section class="style-step" aria-labelledby="style-genre-title">
      <h2 id="style-genre-title" class="section-title">第二步 · 题材</h2>
      <StyleChoiceGrid v-model="genreId" :items="lib.genres" label="题材" :tone-offset="4" />
    </section>

    <p class="note">
      <template v-if="medium && genre">{{ medium.name }} · {{ genre.name }}：{{ genre.description }}。</template>
      <template v-else-if="medium">已选媒介 {{ medium.name }}，还没有选择题材。</template>
      <template v-else-if="genre">已选题材 {{ genre.name }}，还没有选择媒介。</template>
      <template v-else>还没有选择媒介和题材。</template>
      媒介决定画风词与视频质感，题材决定角色形象、场景氛围和叙事节奏；AI 提取角色 / 道具 / 场景、生成三视图与参考图、拆分镜和文生图都会遵循它们。
    </p>

    <section class="style-model" aria-labelledby="style-model-title">
      <h2 id="style-model-title" class="section-title">视频模型</h2>
      <div class="chip-group" role="radiogroup" aria-label="视频模型">
        <button
          v-for="m in models"
          :key="m.key"
          type="button"
          class="chip"
          role="radio"
          :aria-checked="m.key === modelKey ? 'true' : 'false'"
          :aria-pressed="m.key === modelKey ? 'true' : 'false'"
          @click="modelKey = m.key"
        >{{ m.name }} · {{ m.note }}</button>
      </div>
      <p class="note">
        拆分镜按所选模型的时长装段：每段约 {{ currentModel ? currentModel.max_duration : 15 }} 秒、一段一次视频生成，换模型后重新拆分镜才会按新时长装段。
        <template v-if="currentModel && currentModel.cost_multiplier > 1">该模型每次生成消耗 {{ currentModel.cost_multiplier }} 倍额度。</template>
      </p>
    </section>

    <section class="style-model" aria-labelledby="style-narration-title">
      <h2 id="style-narration-title" class="section-title">旁白风格</h2>
      <div class="chip-group" role="radiogroup" aria-label="旁白风格">
        <button
          v-for="n in narrationStyles"
          :key="n.key"
          type="button"
          class="chip"
          role="radio"
          :aria-checked="n.key === narrationKey ? 'true' : 'false'"
          :aria-pressed="n.key === narrationKey ? 'true' : 'false'"
          @click="narrationKey = n.key"
        >{{ n.name }} · {{ n.note }}</button>
      </div>
      <p class="note">
        决定成片里旁白念多少。拆分镜照旧按原文拆，再按这里的风格决定哪些旁白念出来；对白、心声不受影响，被省略的旁白在分镜详情里能看到。
        改了之后重新拆分镜才生效。
      </p>
    </section>
  </ProjectPage>
</template>

<script>
/**
 * 项目风格：两步选择——媒介（真人实拍 / 3D 国漫 / 2D 动漫，2D 再选子画风）+ 题材（11 套）——与视频模型。
 * 保存到作品的 medium / genre / video_model 字段（旧 style 字段清空，兼容映射见 components/project/styleLibrary.js），
 * store 里的当前作品同步更新。视频模型决定拆分镜每段的时长（backend/core/video_models.py），默认 Seedance 2.0 Fast。
 */
import { mapState } from 'vuex'
import { api } from '@/api'
import { runAction, toastError } from '@/utils/notify'
import { loadVideoModels, findModel, DEFAULT_VIDEO_MODEL } from '@/components/project/videoModels'
import { NARRATION_STYLES, narrationStyleOf } from '@/components/project/narrationStyles'
import { loadStyleLibrary } from '@/components/project/styleLoader'
import { EMPTY_LIBRARY, findMedium, findGenre, mediumGroup, projectStyle } from '@/components/project/styleLibrary'
import StyleChoiceGrid from '@/components/project/StyleChoiceGrid.vue'
import { suggestionLabel } from '@/components/project/styleSuggest'
import ProjectPage from './ProjectPage.vue'

export default {
  name: 'StylePage',
  components: { ProjectPage, StyleChoiceGrid },
  props: { pid: { type: String, required: true }, ep: { type: String, default: '' } },
  data() {
    return { lib: EMPTY_LIBRARY, mediumId: '', genreId: '', saving: false, suggesting: false, suggestion: null, models: [], modelKey: DEFAULT_VIDEO_MODEL,
      narrationStyles: NARRATION_STYLES, narrationKey: 'drama' }
  },
  computed: {
    ...mapState('project', { project: 'current' }),
    saved() { return projectStyle(this.lib, this.project) },
    savedMediumId() { return this.saved.medium ? this.saved.medium.id : '' },
    savedGenreId() { return this.saved.genre ? this.saved.genre.id : '' },
    /** 作品没有保存过媒介（也没有旧风格可映射）：页面默认选中缺省媒介并提示，不允许静默为空 */
    mediumUnset() { return !!this.project && !this.savedMediumId },
    savedModel() { return (this.project && this.project.video_model) || DEFAULT_VIDEO_MODEL },
    savedNarration() { return narrationStyleOf(this.project) },
    fallbackMediumId() { return (this.lib && this.lib.fallback_medium) || 'realistic' },
    medium() { return findMedium(this.lib, this.mediumId) },
    genre() { return findGenre(this.lib, this.genreId) },
    group() { return mediumGroup(this.lib, this.mediumId) },
    /** 第一行选中的大类；选 2D 时把子画风设为该类第一个 */
    groupId: {
      get() { return this.group ? this.group.id : '' },
      set(id) {
        const m = findMedium(this.lib, id)
        this.mediumId = m ? m.id : ''
      }
    },
    subMediums() { return this.group && this.group.mediums.length > 1 ? this.group.mediums : [] },
    currentModel() { return findModel(this.models, this.modelKey) },
    suggestionText() { return suggestionLabel(this.suggestion) },
    styleChanged() {
      return (!!this.mediumId || !!this.genreId) &&
        (this.mediumId !== this.savedMediumId || this.genreId !== this.savedGenreId)
    },
    dirty() { return this.styleChanged || this.modelKey !== this.savedModel || this.narrationKey !== this.savedNarration }
  },
  watch: {
    savedMediumId: { immediate: true, handler(v) { this.mediumId = v || this.fallbackMediumId } },
    fallbackMediumId() { if (!this.savedMediumId) this.mediumId = this.fallbackMediumId },
    savedGenreId: { immediate: true, handler(v) { this.genreId = v } },
    savedModel: { immediate: true, handler(v) { this.modelKey = v } },
    savedNarration: { immediate: true, handler(v) { this.narrationKey = v } }
  },
  created() {
    loadStyleLibrary().then(lib => { this.lib = lib }, e => toastError(e, '风格库加载失败'))
    loadVideoModels().then(v => { this.models = v }, e => toastError(e, '视频模型列表加载失败'))
  },
  methods: {
    /** AI 识别：读本集小说推荐媒介和题材，选中后由用户确认保存（不直接写库） */
    async suggest() {
      this.suggesting = true
      try {
        const res = await api.project.suggestStyle(this.pid, { video_set_id: this.ep || '' })
        const s = res && res.data
        if (s) {
          this.suggestion = s
          this.mediumId = s.medium
          const g = findGenre(this.lib, s.genre_id)
          this.genreId = g ? g.id : this.genreId
        }
      } catch (e) {
        toastError(e, 'AI 识别失败')
      } finally {
        this.suggesting = false
      }
    },
    async save() {
      const fields = { video_model: this.modelKey, narration_style: this.narrationKey }
      // 只改视频模型时不带风格字段：否则待识别的作品会被记成“用户已选”，不再自动识别
      if (this.styleChanged && this.medium) fields.medium = this.medium.id
      if (this.styleChanged && this.genre) fields.genre = this.genre.genre
      // 新字段齐全后旧 style 不再参与解析，清空避免误导
      if (this.medium && this.genre && this.project && this.project.style) fields.style = ''
      this.saving = true
      const ok = await runAction(() => api.project.update(this.pid, fields), {
        success: '风格已保存，后续生成都会遵循它',
        error: '保存失败'
      })
      this.saving = false
      if (ok) {
        // 手动保存即确认：以用户选择为准，之后不再自动识别覆盖（后端同样记为 user）
        const sourced = (fields.medium || fields.genre) ? { style_source: 'user' } : {}
        this.$store.commit('project/SET_PROJECT', { ...this.project, ...fields, ...sourced })
        this.suggestion = null
      }
    }
  }
}
</script>

<style scoped>
.style-ai { margin: 0 0 16px; padding: 10px 14px; border-radius: var(--radius, 8px); border: 1px solid var(--line); line-height: 1.6; }
.style-alert { margin: 0 0 16px; padding: 10px 14px; border-radius: var(--radius, 8px); color: var(--warn); border: 1px solid var(--warn); line-height: 1.6; }
.style-step { display: flex; flex-direction: column; gap: 12px; margin-bottom: 28px; }
.style-model { display: flex; flex-direction: column; gap: 10px; margin-top: 28px; }
</style>
