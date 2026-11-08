<template>
  <ProjectPage title="管理剧集">
    <template #actions>
      <BaseButton variant="primary" @click="create">新建一集</BaseButton>
    </template>

    <div class="table-wrap">
      <el-table v-loading="loading" :data="episodes" empty-text="还没有剧集。新建一集后，分镜会按集管理。">
        <el-table-column prop="name" label="剧集" min-width="160" />
        <el-table-column prop="shot_count" label="镜头" width="100" />
        <el-table-column prop="video_count" label="已出视频" width="110" />
        <el-table-column label="操作" min-width="260">
          <template slot-scope="{ row }">
            <BaseButton variant="text" :to="{ path: `/projects/${pid}/shots`, query: { ep: row.id } }">进入</BaseButton>
            <BaseButton variant="text" @click="rename(row)">重命名</BaseButton>
            <BaseButton variant="text" :loading="exportingId === row.id" @click="exportJianying(row)">导出剪映</BaseButton>
            <BaseButton variant="text" @click="remove(row)">删除</BaseButton>
          </template>
        </el-table-column>
      </el-table>
    </div>
  </ProjectPage>
</template>

<script>
/** 剧集（后端“视频集”）列表：新建、重命名、导出剪映、删除。数据存在 store，侧栏剧集选择器同步更新。 */
import { mapState } from 'vuex'
import { api } from '@/api'
import { confirmDelete, promptText } from '@/utils/dialogs'
import ProjectPage from './ProjectPage.vue'

export default {
  name: 'EpisodesPage',
  components: { ProjectPage },
  props: { pid: { type: String, required: true }, ep: { type: String, default: '' } },
  data() {
    return { loading: false, exportingId: '' }
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
      } finally {
        this.loading = false
      }
    },
    async create() {
      const name = await promptText('剧集名称', '新建一集', `第 ${this.episodes.length + 1} 集`)
      if (!name) return
      try {
        await api.videoSet.create(this.pid, name)
        this.$message.success('已创建')
        this.refresh()
      } catch (e) { /* 拦截器已提示 */ }
    },
    async rename(row) {
      const name = await promptText('新名称', '重命名', row.name)
      if (!name || name === row.name) return
      try {
        await api.videoSet.rename(row.id, name)
        this.refresh()
      } catch (e) { /* 拦截器已提示 */ }
    },
    async remove(row) {
      if (!(await confirmDelete(`删除“${row.name}”及其下所有分镜？此操作无法恢复。`))) return
      try {
        await api.videoSet.delete(row.id)
        this.$message.success('已删除')
        this.refresh()
      } catch (e) { /* 拦截器已提示 */ }
    },
    async exportJianying(row) {
      this.exportingId = row.id
      try {
        const res = await api.export.jianying(this.pid, row.id)
        if (res && res.ok) this.$message.success(res.msg || '已导出到剪映')
        else this.$message.error((res && res.msg) || '导出失败')
      } catch (e) {
        // 拦截器已提示
      } finally {
        this.exportingId = ''
      }
    }
  }
}
</script>
