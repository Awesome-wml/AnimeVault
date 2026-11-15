<template>
  <span class="act-row">
    <el-tooltip v-for="b in buttons" :key="b.key" :content="b.reason" :disabled="!b.reason" placement="top">
      <span>
        <el-button :type="text ? 'text' : (b.danger ? 'danger' : '')" :size="size" :disabled="b.disabled"
                   :class="{ 'act-danger': text && b.danger }" :data-testid="'act-' + b.key"
                   @click="$emit('action', b.key)">{{ b.label }}</el-button>
      </span>
    </el-tooltip>
  </span>
</template>

<script>
/** 授权操作按钮组：按状态机禁用不合法的按钮。只负责展示和发出 action 事件。 */
import { availableActions, disabledReason } from '@/utils/license'

const LABELS = { extend: '延期', suspend: '停用', resume: '恢复', revoke: '吊销' }

export default {
  name: 'LicenseActionButtons',
  props: {
    status: { type: String, required: true },
    size: { type: String, default: 'mini' },
    /** 文字按钮样式（表格行内更紧凑） */
    text: { type: Boolean, default: false },
    only: { type: Array, default: () => ['extend', 'suspend', 'resume', 'revoke'] }
  },
  computed: {
    buttons() {
      const ok = availableActions(this.status)
      return this.only.map(key => ({
        key, label: LABELS[key], danger: key === 'revoke',
        disabled: !ok[key], reason: ok[key] ? '' : disabledReason(this.status, key)
      }))
    }
  }
}
</script>

<style scoped>
.act-danger, .act-danger:hover { color: var(--seal) !important; }
.act-danger.is-disabled { color: var(--ink-soft) !important; }
.act-row { display: inline-flex; flex-wrap: nowrap; align-items: center; gap: 6px; white-space: nowrap; }
</style>
