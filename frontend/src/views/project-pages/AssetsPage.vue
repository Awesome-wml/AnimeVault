<template>
  <ProjectPage :title="meta.title" :subtitle="meta.subtitle">
    <LegacyPanel>
      <AssetPanel :key="kind" :project-id="pid" :initial-tab="kind" />
    </LegacyPanel>
  </ProjectPage>
</template>

<script>
// 角色 / 场景 / 道具共用。一期沿用旧 AssetPanel，二期（T-197）改用 AssetCard 网格。
import ProjectPage from './ProjectPage.vue'
import LegacyPanel from '@/components/legacy/LegacyPanel.vue'
import AssetPanel from '@/views/project/AssetPanel.vue'

const KINDS = {
  character: { title: '角色', subtitle: '生成三视图、绑定音色，让人物在每一镜里都认得出。' },
  scene: { title: '场景', subtitle: '为场景生成参考图，分镜会自动引用。' },
  prop: { title: '道具', subtitle: '为道具生成参考图，分镜会自动引用。' }
}

export default {
  name: 'AssetsPage',
  components: { ProjectPage, LegacyPanel, AssetPanel },
  props: {
    pid: { type: String, required: true },
    ep: { type: String, default: '' },
    kind: { type: String, required: true }
  },
  computed: {
    meta() { return KINDS[this.kind] || KINDS.character }
  },
  beforeDestroy() {
    this.$store.dispatch('project/refreshCounts')
  }
}
</script>
