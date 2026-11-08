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
  </ProjectPage>
</template>

<script>
/** 项目风格（题材）。保存到作品的 style / genre 字段，store 里的当前作品同步更新。 */
import { mapState } from 'vuex'
import { api, STYLE_LIBRARY } from '@/api'
import { runAction } from '@/utils/notify'
import ProjectPage from './ProjectPage.vue'

export default {
  name: 'StylePage',
  components: { ProjectPage },
  props: { pid: { type: String, required: true }, ep: { type: String, default: '' } },
  data() {
    return { styles: STYLE_LIBRARY, selectedId: '', saving: false }
  },
  computed: {
    ...mapState('project', { project: 'current' }),
    savedId() { return (this.project && this.project.style) || '' },
    selected() { return this.styles.find(s => s.id === this.selectedId) || null },
    dirty() { return !!this.selectedId && this.selectedId !== this.savedId }
  },
  watch: {
    savedId: { immediate: true, handler(v) { this.selectedId = v } }
  },
  methods: {
    async save() {
      const s = this.selected
      if (!s) return
      this.saving = true
      const ok = await runAction(() => api.project.update(this.pid, { genre: s.genre, style: s.id }), {
        success: '风格已保存，后续生成都会遵循它',
        error: '保存失败'
      })
      this.saving = false
      if (ok) this.$store.commit('project/SET_PROJECT', { ...this.project, style: s.id, genre: s.genre })
    }
  }
}
</script>
