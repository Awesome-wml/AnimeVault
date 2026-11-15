<template>
  <span class="status-tag" :class="'status-tag--' + meta.tone" :data-status="status">
    <i class="status-tag__dot"></i>{{ meta.label }}
  </span>
</template>

<script>
/**
 * 状态标签：授权（pending 灰、active 绿、suspended 橙、revoked 红、expired 暗灰）；
 * kind="request" 时按申请单状态（待处理橙、已签发绿、已驳回灰）；kind="device" 时 status 传 当前在线/已绑定/已解绑 的 key。
 */
import { deviceStateMeta, requestStatusMeta, statusMeta } from '@/utils/license'

export default {
  name: 'StatusTag',
  props: {
    status: { type: String, default: '' },
    kind: { type: String, default: 'license' }
  },
  computed: {
    meta() {
      if (this.kind === 'request') return requestStatusMeta(this.status)
      if (this.kind === 'device') return deviceStateMeta({ bound: this.status !== 'unbound', is_current: this.status === 'current' })
      return statusMeta(this.status)
    }
  }
}
</script>

<style scoped>
.status-tag {
  display: inline-flex; align-items: center; gap: 6px; padding: 1px 10px;
  border-radius: 999px; font-size: var(--fs-caption); line-height: 22px; white-space: nowrap;
  border: 1px solid currentColor; background: var(--surface);
}
.status-tag__dot { width: 6px; height: 6px; border-radius: 50%; background: currentColor; }
.status-tag--grey { color: var(--st-grey); }
.status-tag--green { color: var(--st-green); }
.status-tag--orange { color: var(--st-orange); }
.status-tag--red { color: var(--st-red); }
.status-tag--dark { color: var(--st-dark); background: var(--side); }
</style>
