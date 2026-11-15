<template>
  <section class="license-info" aria-label="授权信息">
    <dl class="license-info__list">
      <div class="license-info__row">
        <dt>状态</dt>
        <dd :class="'is-' + state">{{ stateText }}</dd>
      </div>
      <div class="license-info__row">
        <dt>套餐</dt>
        <dd>{{ plan }}</dd>
      </div>
      <div class="license-info__row">
        <dt>到期时间</dt>
        <dd>{{ expiry }}<span v-if="remain" class="license-info__remain">（{{ remain }}）</span></dd>
      </div>
      <div v-if="graceUntil" class="license-info__row">
        <dt>请在此前联网</dt>
        <dd>{{ graceUntil }}</dd>
      </div>
      <div v-if="status.last_renew_ok_at" class="license-info__row">
        <dt>上次续租</dt>
        <dd>{{ lastRenew }}</dd>
      </div>
      <div v-if="machineCode" class="license-info__row">
        <dt>本机机器码</dt>
        <dd class="license-info__mono">{{ machineCode }}</dd>
      </div>
    </dl>
    <div v-if="$slots.actions" class="license-info__actions"><slot name="actions"></slot></div>
  </section>
</template>

<script>
/** 授权信息展示：状态、套餐、到期时间、机器码。入参是 /api/license/status 的返回。 */
import { daysLeft, formatDateTime, formatExpiry, planLabel, stateLabel } from './license'

export default {
  name: 'LicenseInfoCard',
  props: {
    status: { type: Object, default: () => ({}) }
  },
  computed: {
    state() { return this.status.state || 'unactivated' },
    stateText() { return stateLabel(this.state) },
    plan() { return planLabel(this.status.plan) },
    expiry() { return formatExpiry(this.status.expires_at) },
    machineCode() { return this.status.machine_code || '' },
    graceUntil() { return this.state === 'grace' ? formatDateTime(this.status.grace_until) : '' },
    lastRenew() { return formatDateTime(this.status.last_renew_ok_at) },
    remain() {
      const d = daysLeft(this.status.expires_at)
      if (d === null || this.state !== 'valid') return ''
      return d <= 0 ? '今天到期' : `还剩 ${d} 天`
    }
  }
}
</script>

<style scoped>
.license-info { display: flex; flex-direction: column; gap: 16px; max-width: 560px; }
.license-info__list {
  border: 1px solid var(--line);
  border-radius: var(--radius);
  background: var(--surface);
}
.license-info__row {
  display: flex;
  gap: 16px;
  padding: 12px 16px;
  font-size: var(--fs-body);
}
.license-info__row + .license-info__row { border-top: 1px solid var(--line); }
.license-info__row dt { flex: none; width: 88px; color: var(--ink-muted); }
.license-info__row dd { min-width: 0; word-break: break-all; }
.license-info__row dd.is-valid { color: var(--ok); }
.license-info__row dd.is-grace { color: var(--warn); }
.license-info__row dd.is-expired, .license-info__row dd.is-invalid, .license-info__row dd.is-machine_mismatch,
.license-info__row dd.is-suspended, .license-info__row dd.is-revoked, .license-info__row dd.is-lease_expired,
.license-info__row dd.is-session_conflict, .license-info__row dd.is-clock_rollback { color: var(--seal); }
.license-info__remain { color: var(--ink-muted); }
.license-info__mono { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; letter-spacing: .04em; }
.license-info__actions { display: flex; gap: 8px; }
</style>
