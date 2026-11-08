<template>
  <div class="page" v-loading="loading">
    <PageHeader title="全部作品">
      <template #actions>
        <BaseButton variant="primary" @click="showNew = true">新建作品</BaseButton>
      </template>
    </PageHeader>

    <div v-if="projects.length" class="card-grid card-grid--lg">
      <AssetCard
        v-for="p in projects"
        :key="p.id"
        size="lg"
        :title="p.name"
        :meta="metaOf(p)"
        :tone="p.id"
        placeholder="封面"
        :to="entryOf(p)"
      >
        <template #actions>
          <BaseButton variant="text" :aria-label="`删除《${p.name}》`" @click="remove(p)">删除</BaseButton>
        </template>
      </AssetCard>
    </div>

    <EmptyState
      v-else-if="!loading"
      seal="戏"
      title="还没有作品"
      description="新建一部作品，贴进小说就能开始。"
    />

    <NewProjectDialog :visible.sync="showNew" />
  </div>
</template>

<script>
import { api } from '@/api'
import { confirmDelete } from '@/utils/dialogs'
import NewProjectDialog from '@/components/project/NewProjectDialog.vue'
import { projectMeta, projectEntry, createdAt } from '@/components/project/meta'

export default {
  name: 'WorksPage',
  components: { NewProjectDialog },
  data() {
    return { loading: true, projects: [], showNew: false }
  },
  created() {
    this.load()
  },
  methods: {
    metaOf: projectMeta,
    entryOf: projectEntry,
    async load() {
      this.loading = true
      try {
        const list = await api.project.list()
        this.projects = (Array.isArray(list) ? list : []).slice().sort((a, b) => createdAt(b) - createdAt(a))
      } catch (e) {
        this.projects = []
      } finally {
        this.loading = false
      }
    },
    async remove(p) {
      if (!(await confirmDelete(`删除《${p.name}》后无法恢复。`, '删除作品'))) return
      try {
        await api.project.delete(p.id)
        this.$message.success('已删除')
        this.load()
      } catch (e) {
        // 拦截器已提示
      }
    }
  }
}
</script>
