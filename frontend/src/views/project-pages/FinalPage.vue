<template>
  <ProjectPage title="成片" :subtitle="episode ? episode.name : ''">
    <EmptyState title="成片预览二期实现" description="成片预览需要后端支持，现在可以把已生成的镜头视频导出到剪映精修，或下载整部作品的字幕。">
      <template #actions>
        <BaseButton variant="primary" :loading="exporting" @click="exportJianying">导出到剪映</BaseButton>
        <BaseButton :loading="srtLoading" @click="downloadSrt">下载字幕</BaseButton>
      </template>
    </EmptyState>
  </ProjectPage>
</template>

<script>
import { mapGetters } from 'vuex'
import { api } from '@/api'
import ProjectPage from './ProjectPage.vue'

export default {
  name: 'FinalPage',
  components: { ProjectPage },
  props: { pid: { type: String, required: true }, ep: { type: String, default: '' } },
  data() {
    return { exporting: false, srtLoading: false }
  },
  computed: {
    ...mapGetters('project', { episode: 'currentEpisode' })
  },
  methods: {
    async exportJianying() {
      this.exporting = true
      try {
        const res = await api.export.jianying(this.pid, this.ep)
        if (res && res.ok) this.$message.success(res.msg || '已导出到剪映')
        else this.$message.error((res && res.msg) || '导出失败')
      } catch (e) {
        // 拦截器已提示
      } finally {
        this.exporting = false
      }
    },
    async downloadSrt() {
      this.srtLoading = true
      try {
        const res = await api.tts.exportSrt(this.pid)
        if (res && res.message) this.$message.success(res.message)
        window.open(api.tts.downloadSrt(this.pid), '_blank')
      } catch (e) {
        // 拦截器已提示
      } finally {
        this.srtLoading = false
      }
    }
  }
}
</script>
