<template>
  <span class="status-tag" :class="'status-tag--' + meta.tone" :data-status="status">
    <i class="status-tag__dot"></i>{{ meta.label }}
  </span>
</template>

<script>
/** 授权状态标签：pending 灰、active 绿、suspended 橙、revoked 红、expired 暗灰 */
import { statusMeta } from '@/utils/license'

export default {
  name: 'StatusTag',
  props: { status: { type: String, default: '' } },
  computed: { meta() { return statusMeta(this.status) } }
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
