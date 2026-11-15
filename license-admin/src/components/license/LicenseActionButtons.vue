<template>
  <span class="inline-actions">
    <el-tooltip v-for="b in buttons" :key="b.key" :content="b.reason" :disabled="!b.reason" placement="top">
      <span>
        <el-button :type="b.danger ? 'danger' : ''" :size="size" :disabled="b.disabled" :data-testid="'act-' + b.key"
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
