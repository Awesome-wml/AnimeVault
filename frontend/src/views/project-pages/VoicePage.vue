<template>
  <ProjectPage title="配音与字幕">
    <EmptyState compact title="配音与字幕页二期实现。下面可以先为角色绑定 TTS 音色；字幕在分镜页导出。" />
    <LegacyPanel>
      <CharacterPanel :project-id="pid" />
    </LegacyPanel>
  </ProjectPage>
</template>

<script>
// 角色音色绑定沿用旧 CharacterPanel，保证功能不丢；二期（T-197）重做本页
import ProjectPage from './ProjectPage.vue'
import LegacyPanel from '@/components/legacy/LegacyPanel.vue'
import CharacterPanel from '@/views/project/CharacterPanel.vue'

export default {
  name: 'VoicePage',
  components: { ProjectPage, LegacyPanel, CharacterPanel },
  props: { pid: { type: String, required: true }, ep: { type: String, default: '' } },
  beforeDestroy() {
    this.$store.dispatch('project/refreshCounts')
  }
}
</script>
