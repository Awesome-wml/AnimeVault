<template>
  <div class="devices" data-testid="device-panel">
    <div class="devices__bar">
      <span class="note">设备记录来自客户端激活和续租。解绑后该设备不再占用设备数。</span>
      <el-tooltip v-if="canWrite" :content="kickReason" :disabled="!kickReason" placement="top">
        <span>
          <el-button size="small" type="danger" plain :disabled="!!kickReason" data-testid="kick-open" @click="kickVisible = true">踢下线</el-button>
        </span>
      </el-tooltip>
    </div>

    <BaseTable :data="devices" :loading="loading" empty-text="还没有设备激活过这个授权" data-testid="device-table">
      <el-table-column label="设备" min-width="130">
        <template slot-scope="{ row }">
          <span class="mono small" :title="row.did">{{ row.did }}</span>
          <div class="cell-sub">{{ row.components_count }} 个分量 · {{ (row.components_hint || []).join(' ') }}</div>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="108">
        <template slot-scope="{ row }"><StatusTag kind="device" :status="deviceKey(row)" :data-testid="'device-state-' + row.did" /></template>
      </el-table-column>
      <el-table-column label="首次 / 最近在线" width="150">
        <template slot-scope="{ row }">
          <div class="small">{{ fmt(row.first_seen_at) }}</div>
          <div class="cell-sub">{{ fmt(row.last_seen_at) }}</div>
        </template>
      </el-table-column>
      <el-table-column label="最近 IP / 版本" width="120">
        <template slot-scope="{ row }">
          <div class="small">{{ row.last_ip || '-' }}</div>
          <div class="cell-sub">{{ row.app_version || '-' }}</div>
        </template>
      </el-table-column>
      <el-table-column v-if="canWrite" label="操作" width="76">
        <template slot-scope="{ row }">
          <el-tooltip :content="unbindReason(row)" :disabled="!unbindReason(row)" placement="top">
            <span>
              <el-button type="text" class="danger-text" :disabled="!!unbindReason(row)" :data-testid="'unbind-' + row.did"
                         @click="askUnbind(row)">解绑</el-button>
            </span>
          </el-tooltip>
          <div v-if="!row.bound" class="cell-sub" :title="fmt(row.unbound_at)">{{ fmt(row.unbound_at, false) }}</div>
        </template>
      </el-table-column>
    </BaseTable>

    <ConfirmDialog :visible.sync="kickVisible" title="踢下线" confirm-label="确认踢下线" danger :loading="acting"
                   message="踢下线后，对方下次续租会被要求重新激活（需要用授权码重新激活）；授权本身和设备绑定不变。确认踢下线？"
                   @confirm="doKick" />
    <ConfirmDialog :visible.sync="unbindVisible" title="解绑设备" confirm-label="确认解绑" danger :loading="acting"
                   :message="unbindMessage" @confirm="doUnbind" />
  </div>
</template>

<script>
import { api } from '@/api'
import { can } from '@/config/roles'
import { kickDisabledReason, unbindDisabledReason } from '@/utils/license'
import { formatTime } from '@/utils/time'

/**
 * 授权详情抽屉里的「设备」页签：设备列表、解绑、踢下线。
 * 按钮可用性遵循状态机（已吊销不可操作、无在线会话不可踢、已解绑不可再解绑）；只读角色看不到操作按钮。
 * 操作成功后发出 changed，由抽屉刷新授权（active_sid）和事件时间线。
 */
export default {
  name: 'DevicePanel',
  props: { lic: { type: Object, required: true } },
  data() {
    return { devices: [], loading: false, acting: false, kickVisible: false, unbindVisible: false, target: null }
  },
  computed: {
    canWrite() { return can(this.$store.getters.role, 'license.write') },
    kickReason() { return kickDisabledReason(this.lic) },
    unbindMessage() {
      return this.target && this.target.is_current
        ? '这是当前在线的设备：解绑后会同时把它踢下线，对方下次续租会被要求重新激活。确认解绑？'
        : '解绑后该设备不再占用设备数。确认解绑？'
    }
  },
  watch: { 'lic.lid'() { this.load() } },
  created() { this.load() },
  methods: {
    fmt: formatTime,
    deviceKey(d) { return !d.bound ? 'unbound' : d.is_current ? 'current' : 'bound' },
    unbindReason(d) { return unbindDisabledReason(this.lic, d) },
    async load() {
      this.loading = true
      try { this.devices = (await api.licenses.devices(this.lic.lid)).items || [] } catch (e) { /* 拦截器已提示 */ } finally { this.loading = false }
    },
    askUnbind(d) { this.target = d; this.unbindVisible = true },
    async act(fn, close, okText) {
      this.acting = true
      try {
        await fn()
        close()
        this.$message.success(okText)
        this.$emit('changed')
        this.load()
      } catch (e) {
        // 拦截器已提示；状态已变化（没有会话/已解绑/已吊销）时也关弹窗并刷新
        if (['NO_ACTIVE_SESSION', 'DEVICE_NOT_BOUND', 'INVALID_TRANSITION'].includes(e.code)) { close(); this.$emit('changed'); this.load() }
      } finally { this.acting = false }
    },
    doKick() { return this.act(() => api.licenses.kick(this.lic.lid), () => { this.kickVisible = false }, '已踢下线，对方下次续租需要重新激活') },
    doUnbind() { return this.act(() => api.licenses.unbindDevice(this.lic.lid, this.target.did), () => { this.unbindVisible = false }, '已解绑') }
  }
}
</script>

<style scoped>
.devices { display: flex; flex-direction: column; gap: 12px; }
.devices__bar { display: flex; justify-content: space-between; align-items: center; gap: 12px; }
.danger-text, .danger-text:hover { color: var(--seal); }
.danger-text.is-disabled { color: var(--ink-soft); }
</style>
