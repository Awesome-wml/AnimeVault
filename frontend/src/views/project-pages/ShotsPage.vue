<template>
  <ProjectPage title="分镜" :subtitle="episode ? episode.name : ''">
    <LegacyPanel>
      <ShotPanel :key="ep" :project-id="pid" :video-set-id="ep" />
    </LegacyPanel>
  </ProjectPage>
</template>

<script>
// 一期沿用旧 ShotPanel（随 ?ep= 切换剧集重新加载），二期（T-197）拆成 components/shot/*
import { mapGetters } from 'vuex'
import ProjectPage from './ProjectPage.vue'
import LegacyPanel from '@/components/legacy/LegacyPanel.vue'
import ShotPanel from '@/views/project/ShotPanel.vue'

export default {
  name: 'ShotsPage',
  components: { ProjectPage, LegacyPanel, ShotPanel },
  props: { pid: { type: String, required: true }, ep: { type: String, default: '' } },
  computed: {
    ...mapGetters('project', { episode: 'currentEpisode' })
  }
}
</script>
