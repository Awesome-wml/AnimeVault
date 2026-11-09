<template>
  <ProjectPage title="风格" subtitle="贯穿角色、场景、分镜画面，全片保持统一。">
    <template #actions>
      <BaseButton variant="primary" :loading="saving" :disabled="!dirty" @click="save">保存</BaseButton>
    </template>

    <div class="card-grid card-grid--choice" role="radiogroup" aria-label="题材风格">
      <AssetCard
        v-for="(s, i) in styles"
        :key="s.id"
        :title="s.name"
        :tone="i + 1"
        ratio="4 / 3"
        selectable
        :selected="s.id === selectedId"
        @open="selectedId = s.id"
      />
    </div>

    <p class="note">
      <template v-if="selected">{{ selected.name }}：{{ selected.desc }}。</template>
      <template v-else>还没有选择风格。</template>
      AI 提取角色 / 道具 / 场景、生成三视图与参考图、拆分镜和文生图都会遵循它。
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
  </ProjectPage>
</template>

<script>
/**
 * 项目风格（题材）与视频模型。保存到作品的 style / genre / video_model 字段，store 里的当前作品同步更新。
 * 视频模型决定拆分镜每段的时长（backend/core/video_models.py），默认 Seedance 2.0 Fast。
 */
import { mapState } from 'vuex'
import { api, STYLE_LIBRARY } from '@/api'
import { runAction, toastError } from '@/utils/notify'
import { loadVideoModels, findModel, DEFAULT_VIDEO_MODEL } from '@/components/project/videoModels'
import ProjectPage from './ProjectPage.vue'

export default {
  name: 'StylePage',
  components: { ProjectPage },
  props: { pid: { type: String, required: true }, ep: { type: String, default: '' } },
  data() {
    return { styles: STYLE_LIBRARY, selectedId: '', saving: false, models: [], modelKey: DEFAULT_VIDEO_MODEL }
  },
  computed: {
    ...mapState('project', { project: 'current' }),
    savedId() { return (this.project && this.project.style) || '' },
    savedModel() { return (this.project && this.project.video_model) || DEFAULT_VIDEO_MODEL },
    selected() { return this.styles.find(s => s.id === this.selectedId) || null },
    currentModel() { return findModel(this.models, this.modelKey) },
    dirty() {
      return (!!this.selectedId && this.selectedId !== this.savedId) || this.modelKey !== this.savedModel
    }
  },
  watch: {
    savedId: { immediate: true, handler(v) { this.selectedId = v } },
    savedModel: { immediate: true, handler(v) { this.modelKey = v } }
  },
  created() {
    loadVideoModels().then(v => { this.models = v }, e => toastError(e, '视频模型列表加载失败'))
  },
  methods: {
    async save() {
      const s = this.selected
      const fields = { video_model: this.modelKey }
      if (s) Object.assign(fields, { genre: s.genre, style: s.id })
      this.saving = true
      const ok = await runAction(() => api.project.update(this.pid, fields), {
        success: '风格已保存，后续生成都会遵循它',
        error: '保存失败'
      })
      this.saving = false
      if (ok) this.$store.commit('project/SET_PROJECT', { ...this.project, ...fields })
    }
  }
}
</script>

<style scoped>
.style-model { display: flex; flex-direction: column; gap: 10px; margin-top: 28px; }
</style>
