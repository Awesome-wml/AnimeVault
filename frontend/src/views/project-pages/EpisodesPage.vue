<template>
  <ProjectPage title="管理剧集" :subtitle="episodes.length ? `${episodes.length} 集` : ''">
    <template #actions>
      <BaseButton variant="primary" @click="create">新建一集</BaseButton>
    </template>

    <div class="table-wrap">
      <el-table v-loading="loading" :data="episodes" empty-text="还没有剧集。新建一集后，分镜会按集管理。">
        <el-table-column prop="name" label="剧集" min-width="180" />
        <el-table-column prop="shot_count" label="镜头" width="110" />
        <el-table-column prop="video_count" label="已出视频" width="110" />
        <el-table-column label="操作" min-width="320">
          <template slot-scope="{ row }">
            <div class="inline-actions">
              <BaseButton variant="text" strong :to="{ path: `/projects/${pid}/shots`, query: { ep: row.id } }">进入</BaseButton>
              <BaseButton variant="text" @click="rename(row)">重命名</BaseButton>
              <BaseButton variant="text" :loading="exportingId === row.id" @click="exportOne(row)">导出剪映</BaseButton>
              <BaseButton variant="text" :loading="capcutExportingId === row.id" @click="exportCapcutOne(row)">导出 CapCut</BaseButton>
              <BaseButton variant="text" @click="remove(row)">删除</BaseButton>
            </div>
          </template>
        </el-table-column>
      </el-table>
    </div>
  </ProjectPage>
</template>

<script>
/** 剧集（后端“视频集”）：新建、重命名、导出剪映、删除。数据在 store，侧栏剧集选择器同步更新。 */
import { mapState } from 'vuex'
import { api } from '@/api'
import { confirmDelete, promptText } from '@/utils/dialogs'
import { runAction, toastError } from '@/utils/notify'
import { exportJianying, exportCapcut } from '@/components/project/exports'
import ProjectPage from './ProjectPage.vue'

export default {
  name: 'EpisodesPage',
  components: { ProjectPage },
  props: { pid: { type: String, required: true }, ep: { type: String, default: '' } },
  data() {
    return { loading: false, exportingId: '', capcutExportingId: '' }
  },
  computed: {
    ...mapState('project', ['episodes'])
  },
  created() {
    this.refresh()
  },
  methods: {
    async refresh() {
      this.loading = true
      try {
        await this.$store.dispatch('project/refreshEpisodes', this.pid)
      } catch (e) {
        toastError(e, '剧集列表加载失败')
      } finally {
        this.loading = false
      }
    },
    async create() {
      const name = await promptText('剧集名称', '新建一集', `第 ${this.episodes.length + 1} 集`)
      if (!name) return
      const ok = await runAction(() => api.videoSet.create(this.pid, name), { success: '已创建', error: '创建失败' })
      if (ok) this.refresh()
    },
    async rename(row) {
      const name = await promptText('新名称', '重命名', row.name)
      if (!name || name === row.name) return
      const ok = await runAction(() => api.videoSet.rename(row.id, name), { success: '已重命名', error: '重命名失败' })
      if (ok) this.refresh()
    },
    async remove(row) {
      if (!(await confirmDelete(`删除“${row.name}”及其下所有分镜？此操作无法恢复。`))) return
      const ok = await runAction(() => api.videoSet.delete(row.id), { success: '已删除', error: '删除失败' })
      if (ok) this.refresh()
    },
    async exportOne(row) {
      this.exportingId = row.id
      await exportJianying(this.pid, row.id)
      this.exportingId = ''
    },
    async exportCapcutOne(row) {
      this.capcutExportingId = row.id
      await exportCapcut(this.pid, row.id)
      this.capcutExportingId = ''
    }
  }
}
</script>
