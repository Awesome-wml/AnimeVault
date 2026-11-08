<template>
  <ProjectPage title="小说" subtitle="贴入或让 AI 写一篇，再一键提取角色、场景、道具和分镜。">
    <LegacyPanel>
      <NovelPanel :key="ep" :project-id="pid" :video-set-id="ep" />
    </LegacyPanel>
  </ProjectPage>
</template>

<script>
// 一期沿用旧面板，二期（T-197）重做
import ProjectPage from './ProjectPage.vue'
import LegacyPanel from '@/components/legacy/LegacyPanel.vue'
import NovelPanel from '@/views/project/NovelPanel.vue'

export default {
  name: 'NovelPage',
  components: { ProjectPage, LegacyPanel, NovelPanel },
  props: { pid: { type: String, required: true }, ep: { type: String, default: '' } },
  beforeDestroy() {
    // 提取可能新增了角色/场景/道具，离开时刷新侧栏数量
    this.$store.dispatch('project/refreshCounts')
  }
}
</script>
