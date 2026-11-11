<template>
  <div class="page">
    <PageHeader title="提示词" :subtitle="subtitle" />

    <div class="toolbar">
      <div class="chip-group" role="group" aria-label="类型">
        <button
          v-for="t in typeFilters"
          :key="t.value"
          type="button"
          class="chip"
          :aria-pressed="filterType === t.value ? 'true' : 'false'"
          @click="setType(t.value)"
        >{{ t.short }}</button>
      </div>
      <el-select v-if="categories.length" v-model="filterCategory" size="small" class="prompts__category" aria-label="题材分类" @change="load">
        <el-option label="全部题材" value="" />
        <el-option v-for="c in categories" :key="c" :label="c" :value="c" />
      </el-select>
    </div>

    <PromptTable :list="list" :loading="loading" @view="openView" />

    <PromptEditDialog :visible.sync="viewVisible" :value="viewing" />
  </div>
</template>

<script>
/**
 * 设置 - 提示词（只读）。提示词以后端 core/prompts/system.json、constraints.json 为准，
 * 运行时不读数据库，所以这里只展示，不能编辑；要改就改这两个文件。
 */
import { api } from '@/api'
import PromptTable from '@/components/prompt/PromptTable.vue'
import PromptEditDialog from '@/components/prompt/PromptEditDialog.vue'
import { PROMPT_TYPES, VIDEO_PROMPT_NOTE } from './prompt-types'

export default {
  name: 'PromptsSettings',
  components: { PromptTable, PromptEditDialog },
  data() {
    return {
      typeFilters: [{ value: '', short: '全部' }, ...PROMPT_TYPES],
      subtitle: `提示词在 core/prompts/ 文件里维护，这里只读展示。${VIDEO_PROMPT_NOTE}`,
      filterType: '',
      filterCategory: '',
      categories: [],
      list: [],
      loading: false,
      viewVisible: false,
      viewing: {}
    }
  },
  created() {
    this.load()
  },
  methods: {
    setType(value) {
      this.filterType = value
      this.load()
    },
    async load() {
      this.loading = true
      try {
        const r = await api.prompt.list(this.filterType, this.filterCategory)
        this.list = r.data || []
        if (r.categories) this.categories = r.categories
      } catch (e) {
        this.list = []
      } finally {
        this.loading = false
      }
    },
    openView(row) {
      this.viewing = { ...row }
      this.viewVisible = true
    }
  }
}
</script>

<style scoped>
.prompts__category { width: 140px; }
</style>
