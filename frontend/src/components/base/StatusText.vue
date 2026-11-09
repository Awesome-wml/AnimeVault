<template>
  <span class="status-text" :class="'status-text--' + info.tone">
    <slot>{{ text || info.text }}</slot>
  </span>
</template>

<script>
/** 状态文字：只传 status（见 status.js），颜色与文案在一处定义。n 用于替换文案里的 {n}；传对象时按键替换（如额度的 {plan} {used}）。 */
import { statusInfo } from './status'

export default {
  name: 'StatusText',
  props: {
    status: { type: String, required: true },
    n: { type: [Number, String, Object], default: undefined },
    text: { type: String, default: '' }
  },
  computed: {
    info() { return statusInfo(this.status, this.n) }
  }
}
</script>

<style scoped>
.status-text { font-size: inherit; white-space: nowrap; }
.status-text--ok { color: var(--ok); }
.status-text--warn { color: var(--warn); }
.status-text--seal { color: var(--seal); }
.status-text--muted { color: var(--ink-muted); }
.status-text--ink { color: var(--ink); }
</style>
