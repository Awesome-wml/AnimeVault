<template>
  <ProjectPage title="成片" :subtitle="subtitle">
    <template #actions>
      <BaseButton :loading="srtLoading" @click="downloadSrt">下载字幕</BaseButton>
      <BaseButton variant="primary" :loading="exporting" @click="exportJianying">导出到剪映</BaseButton>
    </template>

    <SequencePlayer v-loading="loading" :items="clips" empty-text="按镜头顺序预览：这一集还没有生成好的视频" />

    <p v-if="shots.length" class="note">
      <template v-if="missing">还有 {{ missing }} 个镜头没有视频，导出时只包含已有视频的镜头。</template>
      <template v-else>所有镜头都有视频了，可以导出到剪映精修。</template>
    </p>
  </ProjectPage>
</template>

<script>
/** 成片：按镜头顺序连续预览当前剧集已生成的视频；导出剪映草稿；下载整部作品字幕。 */
import { mapGetters } from 'vuex'
import { api } from '@/api'
import { toastError } from '@/utils/notify'
import { exportJianying, downloadSrt } from '@/components/project/exports'
import SequencePlayer from '@/components/shot/SequencePlayer.vue'
import ProjectPage from './ProjectPage.vue'

export default {
  name: 'FinalPage',
  components: { ProjectPage, SequencePlayer },
  props: { pid: { type: String, required: true }, ep: { type: String, default: '' } },
  data() {
    return { loading: false, shots: [], exporting: false, srtLoading: false }
  },
  computed: {
    ...mapGetters('project', { episode: 'currentEpisode' }),
    episodeId() { return this.ep || (this.episode ? this.episode.id : '') },
    clips() {
      return this.shots.filter(s => s.video_path).map(s => ({ src: api.staticUrl(s.video_path), label: s.shot_no }))
    },
    missing() { return this.shots.length - this.clips.length },
    subtitle() {
      const parts = this.episode ? [this.episode.name] : []
      if (this.shots.length) parts.push(`已有 ${this.clips.length} / ${this.shots.length} 个镜头的视频`)
      return parts.join(' · ')
    }
  },
  watch: {
    episodeId: { immediate: true, handler: 'load' }
  },
  methods: {
    async load() {
      this.loading = true
      try {
        const list = await api.shot.list(this.pid, this.episodeId)
        this.shots = Array.isArray(list) ? list : []
      } catch (e) {
        toastError(e, '分镜加载失败')
      } finally {
        this.loading = false
      }
    },
    async exportJianying() {
      this.exporting = true
      await exportJianying(this.pid, this.episodeId)
      this.exporting = false
    },
    async downloadSrt() {
      this.srtLoading = true
      await downloadSrt(this.pid)
      this.srtLoading = false
    }
  }
}
</script>
