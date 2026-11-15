<template>
  <el-drawer :visible="visible" :with-header="true" title="授权详情" size="560px" append-to-body
             @update:visible="v => $emit('update:visible', v)" @open="load">
    <div v-loading="loading" class="drawer" data-testid="license-drawer">
      <template v-if="lic">
        <div class="drawer__head">
          <b class="mono" data-testid="drawer-lid">{{ lic.lid }}</b>
          <StatusTag :status="lic.status" />
        </div>

        <section class="drawer__sec">
          <h3 class="section-title">基本信息</h3>
          <el-descriptions :column="1" size="small" border>
            <el-descriptions-item label="邮箱">{{ lic.email || '-' }}</el-descriptions-item>
            <el-descriptions-item label="套餐">{{ planText }}</el-descriptions-item>
            <el-descriptions-item label="功能点">{{ (lic.features || []).join('、') || '-' }}</el-descriptions-item>
            <el-descriptions-item label="设备数上限">{{ lic.dev_max }}</el-descriptions-item>
            <el-descriptions-item label="绑定机器码分量">{{ (lic.machine_components || []).length }} 个</el-descriptions-item>
            <el-descriptions-item label="签发时间">{{ fmt(lic.issued_at) }}</el-descriptions-item>
            <el-descriptions-item label="到期时间">
              <span :class="'expiry--' + level">{{ fmt(lic.expires_at) }}</span>
              <span v-if="level === 'soon'" class="expiry-flag">即将到期</span>
            </el-descriptions-item>
            <el-descriptions-item label="激活时间">{{ lic.activated_at ? fmt(lic.activated_at) : '未激活' }}</el-descriptions-item>
            <el-descriptions-item label="最近在线">{{ lastSeen }}</el-descriptions-item>
            <el-descriptions-item label="授权码版本">v{{ lic.code_version }}</el-descriptions-item>
            <el-descriptions-item label="备注">{{ lic.note || '-' }}</el-descriptions-item>
          </el-descriptions>
        </section>

        <section class="drawer__sec">
          <h3 class="section-title">授权码</h3>
          <LicenseCode :code="lic.code_display || lic.code || ''" foldable />
        </section>

        <section v-if="canWrite" class="drawer__sec">
          <h3 class="section-title">操作</h3>
          <LicenseActionButtons :status="lic.status" size="small" @action="a => $emit('action', a, lic)" />
        </section>

        <section class="drawer__sec">
          <h3 class="section-title">事件时间线</h3>
          <el-timeline v-if="events.length" data-testid="event-timeline">
            <el-timeline-item v-for="(ev, i) in events" :key="i" :timestamp="fmt(ev.at)" placement="top">
              <b>{{ evLabel(ev.type) }}</b>
              <div class="note">{{ summary(ev) }}<span v-if="ev.ip"> · IP {{ ev.ip }}</span></div>
            </el-timeline-item>
          </el-timeline>
          <p v-else class="note">暂无事件</p>
        </section>
      </template>
    </div>
  </el-drawer>
</template>

<script>
import { api } from '@/api'
import { can } from '@/config/roles'
import { planLabel } from '@/config/plans'
import { eventLabel, eventSummary, expiryLevel, lastSeenText } from '@/utils/license'
import { formatTime } from '@/utils/time'
import LicenseCode from './LicenseCode.vue'
import LicenseActionButtons from './LicenseActionButtons.vue'

export default {
  name: 'LicenseDrawer',
  components: { LicenseCode, LicenseActionButtons },
  props: {
    visible: { type: Boolean, default: false },
    lid: { type: String, default: '' }
  },
  data() { return { lic: null, events: [], loading: false } },
  computed: {
    canWrite() { return can(this.$store.getters.role, 'license.write') },
    planText() { return planLabel(this.lic && this.lic.plan) },
    level() { return this.lic ? expiryLevel(this.lic.expires_at, this.lic.status) : 'normal' },
    lastSeen() { return lastSeenText(this.lic, formatTime) }
  },
  methods: {
    fmt: formatTime,
    evLabel: eventLabel,
    summary(ev) { return eventSummary(ev, t => formatTime(t, false)) },
    async load() {
      if (!this.lid) return
      if (this.lic && this.lic.lid !== this.lid) { this.lic = null; this.events = [] }
      this.loading = true
      try {
        const [lic, evs] = await Promise.all([api.licenses.get(this.lid), api.licenses.events(this.lid)])
        this.lic = lic
        this.events = (evs.items || []).slice().sort((a, b) => (b.at - a.at) || ((b.seq || 0) - (a.seq || 0)))
      } catch (e) { /* 拦截器已提示 */ } finally {
        this.loading = false
      }
    }
  }
}
</script>

<style scoped>
.drawer { padding: 0 20px 28px; display: flex; flex-direction: column; gap: 20px; min-height: 200px; }
.drawer__head { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.drawer__sec { display: flex; flex-direction: column; gap: 10px; }
.section-title { font-size: 15px; font-weight: 600; margin: 0; }
.expiry--soon, .expiry--expired { color: var(--soon); font-weight: 600; }
.expiry-flag { margin-left: 8px; font-size: var(--fs-caption); color: var(--soon); }
</style>
