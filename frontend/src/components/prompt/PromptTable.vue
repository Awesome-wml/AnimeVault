<template>
  <div class="table-wrap">
    <el-table v-loading="loading" :data="list" empty-text="这个类型下还没有提示词。">
      <el-table-column label="名称" min-width="260">
        <template slot-scope="{ row }">
          <div class="prompt-name">
            <span>{{ row.name }}</span>
            <span v-if="flags(row).builtin" class="prompt-tag" data-testid="builtin-tag">内置</span>
          </div>
          <div v-if="note(row)" class="prompt-note">
            <StatusText :status="flags(row).hasUpdate ? 'prompt_has_update' : 'prompt_overriding'" :text="note(row)" />
          </div>
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
      <el-table-column label="操作" width="260">
        <template slot-scope="{ row }">
          <div class="inline-actions">
            <BaseButton v-if="has(row, 'edit')" variant="text" @click="$emit('edit', row)">{{ flags(row).builtin ? '查看/编辑' : '编辑' }}</BaseButton>
            <BaseButton v-if="has(row, 'set-default')" variant="text" @click="$emit('set-default', row)">设为默认</BaseButton>
            <BaseButton v-if="has(row, 'duplicate')" variant="text" @click="$emit('duplicate', row)">复制为自定义</BaseButton>
            <BaseButton
              v-if="has(row, 'restore')"
              variant="text"
              :strong="flags(row).hasUpdate"
              :title="flags(row).hasUpdate ? '代码已有新版本，恢复后使用最新内置内容' : '恢复成代码里的内置内容'"
              @click="$emit('restore', row)"
            >恢复内置</BaseButton>
            <BaseButton v-if="has(row, 'delete')" variant="text" @click="$emit('remove', row)">删除</BaseButton>
          </div>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<script>
/**
 * 提示词列表。只负责展示与发事件：edit / set-default / duplicate / restore / remove，数据请求在页面。
 * 内置行：标“内置”，按钮为 查看/编辑、复制为自定义、恢复内置（代码有新版本时加粗并提示）；
 * 自定义行：设为默认的提示“正在覆盖内置（默认）”。
 */
import { promptTypeShort } from '@/views/settings/prompt-types'
import { promptFlags, promptRowNote, promptActions } from './prompt-state'

export default {
  name: 'PromptTable',
  props: {
    list: { type: Array, default: () => [] },
    loading: Boolean
  },
  methods: {
    typeShort: promptTypeShort,
    flags: promptFlags,
    note: promptRowNote,
    has(row, action) { return promptActions(row).includes(action) }
  }
}
</script>

<style scoped>
.prompt-name { display: flex; align-items: center; gap: 8px; }
.prompt-tag {
  flex: none; padding: 0 6px; border: 1px solid var(--line); border-radius: 4px;
  background: var(--side); color: var(--ink-muted); font-size: var(--fs-caption); line-height: 18px;
}
.prompt-note { font-size: var(--fs-caption); }
</style>
