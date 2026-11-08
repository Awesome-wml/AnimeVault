<template>
  <div class="page">
    <PageHeader title="提示词">
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

    <div class="table-wrap">
      <el-table v-loading="loading" :data="list" empty-text="这个类型下还没有提示词。">
        <el-table-column label="名称" min-width="240">
          <template slot-scope="{ row }">
            <div>{{ row.name }}</div>
            <div v-if="row.content" class="cell-sub" :title="row.content">{{ row.content }}</div>
          </template>
        </el-table-column>
        <el-table-column label="类型" min-width="120">
          <template slot-scope="{ row }">
            {{ typeShort(row.type) }}<span v-if="row.category && row.category !== '通用'" class="muted"> · {{ row.category }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="version" label="版本" width="80" />
        <el-table-column label="默认" width="70">
          <template slot-scope="{ row }">
            <StatusText v-if="row.is_default" status="default" text="是" />
          </template>
        </el-table-column>
        <el-table-column label="操作" width="200">
          <template slot-scope="{ row }">
            <BaseButton variant="text" @click="openEdit(row)">编辑</BaseButton>
            <BaseButton v-if="!row.is_default" variant="text" @click="setDefault(row)">设为默认</BaseButton>
            <BaseButton variant="text" @click="remove(row)">删除</BaseButton>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-dialog append-to-body :title="editing._id ? '编辑提示词' : '新建提示词'" :visible.sync="editVisible" width="640px">
      <div class="form-stack">
        <FormField label="名称" required>
          <el-input v-model="editing.name" />
        </FormField>
        <div class="prompts__row">
          <FormField label="类型" required>
            <el-select v-model="editing.type" placeholder="选择类型">
              <el-option v-for="t in types" :key="t.value" :label="t.label" :value="t.value" />
            </el-select>
          </FormField>
          <FormField label="题材分类">
            <el-select v-model="editing.category" filterable allow-create default-first-option>
              <el-option v-for="c in categoryOptions" :key="c" :label="c" :value="c" />
            </el-select>
          </FormField>
          <FormField label="版本">
            <el-input v-model="editing.version" placeholder="v1.0" />
          </FormField>
        </div>
        <FormField label="内容" required>
          <el-input v-model="editing.content" type="textarea" :rows="12" />
        </FormField>
      </div>
      <template #footer>
        <BaseButton variant="text" @click="editVisible = false">取消</BaseButton>
        <BaseButton variant="primary" :loading="saving" @click="save">保存</BaseButton>
      </template>
    </el-dialog>
  </div>
</template>

<script>
import { api } from '@/api'
import { confirmDelete } from '@/utils/dialogs'
import { PROMPT_TYPES, promptTypeShort } from './prompt-types'

export default {
  name: 'PromptsSettings',
  data() {
    return {
      types: PROMPT_TYPES,
      typeFilters: [{ value: '', short: '全部' }, ...PROMPT_TYPES],
      filterType: '',
      filterCategory: '',
      categories: [],
      list: [],
      loading: false,
      saving: false,
      editVisible: false,
      editing: {}
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
    typeShort: promptTypeShort,
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
      this.editing = row
        ? { ...row }
        : { name: '', version: 'v1.0', type: this.filterType, category: '通用', content: '' }
      this.editVisible = true
    },
    async save() {
      const { name, type, content } = this.editing
      if (!name || !type || !content) {
        this.$message.warning('请填写名称、类型和内容')
        return
      }
      this.saving = true
      try {
        if (this.editing._id) await api.prompt.update(this.editing._id, this.editing)
        else await api.prompt.create(this.editing)
        this.editVisible = false
        this.$message.success('已保存')
        this.load()
      } catch (e) {
        // 拦截器已提示
      } finally {
        this.saving = false
      }
    },
    async setDefault(row) {
      try {
        await api.prompt.update(row._id, { is_default: true })
        this.load()
      } catch (e) { /* 拦截器已提示 */ }
    },
    async remove(row) {
      if (!(await confirmDelete(`删除提示词“${row.name}”？`))) return
      try {
        await api.prompt.delete(row._id)
        this.$message.success('已删除')
        this.load()
      } catch (e) { /* 拦截器已提示 */ }
    }
  }
}
</script>

<style scoped>
.prompts__category { width: 140px; }
.prompts__row { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 16px; }
</style>
