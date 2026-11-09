<template>
  <div class="page">
    <PageHeader title="提示词" :subtitle="subtitle">
      <template #actions>
        <BaseButton variant="primary" @click="openEdit()">新建提示词</BaseButton>
      </template>
    </PageHeader>

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

    <PromptTable
      :list="list"
      :loading="loading"
      @edit="openEdit"
      @set-default="setDefault"
      @duplicate="duplicate"
      @restore="restore"
      @remove="remove"
    />

    <PromptEditDialog
      :visible.sync="editVisible"
      :value="editing"
      :types="types"
      :category-options="categoryOptions"
      :saving="saving"
      @save="save"
    />
  </div>
</template>

<script>
/**
 * 设置 - 提示词。页面只组装：列表（PromptTable）、编辑框（PromptEditDialog）、请求（api.prompt）。
 * 内置提示词由后端启动时从代码同步进库，这里能看、能改内容、能复制为自定义、能恢复；
 * 设为默认的自定义提示词会覆盖同类型内置（列表里会标出）。
 */
import { api } from '@/api'
import { confirmDelete, confirmAction } from '@/utils/dialogs'
import { toastError } from '@/utils/notify'
import PromptTable from '@/components/prompt/PromptTable.vue'
import PromptEditDialog from '@/components/prompt/PromptEditDialog.vue'
import { newPromptDraft, promptPayload } from '@/components/prompt/prompt-state'
import { PROMPT_TYPES, VIDEO_PROMPT_NOTE } from './prompt-types'

export default {
  name: 'PromptsSettings',
  components: { PromptTable, PromptEditDialog },
  data() {
    return {
      types: PROMPT_TYPES,
      typeFilters: [{ value: '', short: '全部' }, ...PROMPT_TYPES],
      subtitle: `内置提示词随代码更新，可以直接修改、复制为自定义或恢复；设为默认的自定义提示词会覆盖同类型的内置。${VIDEO_PROMPT_NOTE}`,
      filterType: '',
      filterCategory: '',
      categories: [],
      list: [],
      loading: false,
      saving: false,
      editVisible: false,
      editing: newPromptDraft()
    }
  },
  computed: {
    categoryOptions() {
      return this.categories.includes('通用') ? this.categories : ['通用', ...this.categories]
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
    openEdit(row) {
      this.editing = row ? { ...row } : newPromptDraft(this.filterType)
      this.editVisible = true
    },
    async save(form) {
      this.saving = true
      try {
        if (form._id) await api.prompt.update(form._id, promptPayload(form))
        else await api.prompt.create(promptPayload(form))
        this.editVisible = false
        this.$message.success('已保存')
        this.load()
      } catch (e) {
        toastError(e)
      } finally {
        this.saving = false
      }
    },
    async setDefault(row) {
      try {
        await api.prompt.update(row._id, { is_default: true })
        this.load()
      } catch (e) { toastError(e) }
    },
    async duplicate(row) {
      try {
        await api.prompt.duplicate(row._id)
        this.$message.success(`已复制为自定义：${row.name}（副本）`)
        this.load()
      } catch (e) { toastError(e) }
    },
    async restore(row) {
      const tip = row.has_update ? '代码已有新版本，' : ''
      if (!(await confirmAction(`${tip}把“${row.name}”恢复成代码里的内置内容？当前修改会被覆盖。`, '恢复内置', '恢复'))) return
      try {
        await api.prompt.restore(row._id)
        this.$message.success('已恢复内置')
        this.load()
      } catch (e) { toastError(e) }
    },
    async remove(row) {
      if (!(await confirmDelete(`删除提示词“${row.name}”？`))) return
      try {
        await api.prompt.delete(row._id)
        this.$message.success('已删除')
        this.load()
      } catch (e) { toastError(e) }
    }
  }
}
</script>

<style scoped>
.prompts__category { width: 140px; }
</style>
