<template>
  <div class="table-wrap">
    <el-table v-loading="loading" :data="list" empty-text="这个类型下没有提示词。">
      <el-table-column label="名称" min-width="260">
        <template slot-scope="{ row }">
          <div class="prompt-name">
            <span>{{ row.name }}</span>
            <span class="prompt-tag">只读</span>
          </div>
          <div v-if="row.content" class="cell-sub" :title="row.content">{{ row.content }}</div>
        </template>
      </el-table-column>
      <el-table-column label="类型" min-width="120">
        <template slot-scope="{ row }">
          {{ typeShort(row.type) }}<span v-if="row.category && row.category !== '通用'" class="muted"> · {{ row.category }}</span>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="100">
        <template slot-scope="{ row }">
          <BaseButton variant="text" @click="$emit('view', row)">查看</BaseButton>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<script>
/** 提示词列表（只读）。只负责展示与发 view 事件；提示词在后端 core/prompts/ 文件里维护。 */
import { promptTypeShort } from '@/views/settings/prompt-types'

export default {
  name: 'PromptTable',
  props: {
    list: { type: Array, default: () => [] },
    loading: Boolean
  },
  methods: {
    typeShort: promptTypeShort
  }
}
</script>

<style scoped>
.prompt-name { display: flex; align-items: center; gap: 8px; }
.prompt-tag {
  flex: none; padding: 0 6px; border: 1px solid var(--line); border-radius: 4px;
  background: var(--side); color: var(--ink-muted); font-size: var(--fs-caption); line-height: 18px;
}
</style>
