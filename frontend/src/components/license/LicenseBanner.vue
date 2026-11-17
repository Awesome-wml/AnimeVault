<template>
  <div v-if="model" class="license-banner" :class="'is-' + model.level" role="status">
    <span class="license-banner__text">{{ model.text }}</span>
    <button v-if="model.action === 'renew'" type="button" class="license-banner__btn" :disabled="checking" @click="renew">
      {{ checking ? '检查中…' : '立即检查' }}
    </button>
    <button v-else-if="model.action === 'activate' && !onActivatePage" type="button" class="license-banner__btn" @click="goActivate">重新激活</button>
  </div>
</template>

<script>
/**
 * 授权全局提示条：宽限期（黄）、只读/时间异常（红）、被其它设备顶掉（红 + 弹窗）。
 * 状态来自路由守卫的 licenseGate 缓存；每 60 秒、每次路由切换时刷新。接口全部走 api.license。
 */
import { api } from '@/api'
import { licenseErrorMessage } from '@/api/license'
import { licenseGate } from '@/router/licenseGuard'
import { toastError, toastSuccess } from '@/utils/notify'
import { ACTIVATE_PATH } from '@/utils/licenseGate'
import { bannerModel, shouldShowDialog, SESSION_CONFLICT_DIALOG } from './banner'

const POLL_MS = 60 * 1000

export default {
  name: 'LicenseBanner',
  data() {
    return { status: null, checking: false, dialogShown: false, timer: null }
  },
  computed: {
    model() {
      return bannerModel(this.status)
    },
    onActivatePage() {
      return this.$route.path === ACTIVATE_PATH
    }
  },
  watch: {
    '$route.path'() { this.refresh(false) },
    model(m) {
      if (!shouldShowDialog(m, this.dialogShown)) {
        if (!m || !m.dialog) this.dialogShown = false
        return
      }
      this.dialogShown = true
      this.showConflictDialog()
    }
  },
  created() {
    this.refresh(false)
    this.timer = setInterval(() => this.refresh(true), POLL_MS)
  },
  beforeDestroy() {
    clearInterval(this.timer)
  },
  methods: {
    async refresh(force) {
      const status = await licenseGate.check({ force })
      if (status) this.status = status
    },
    async renew() {
      if (this.checking) return
      this.checking = true
      try {
        const res = await api.license.renewNow()
        licenseGate.set(res)
        this.status = res
        toastSuccess('授权已更新')
      } catch (e) {
        // 授权接口的错误拦截器不弹提示，这里自己提示；失败后刷新一下状态（服务端拒绝时状态已变）
        toastError(null, licenseErrorMessage(e))
        this.refresh(true)
      } finally {
        this.checking = false
      }
    },
    goActivate() {
      if (this.$route.path !== ACTIVATE_PATH) this.$router.push(ACTIVATE_PATH).catch(() => {})
    },
    showConflictDialog() {
      if (this.$route.path === ACTIVATE_PATH) return
      const d = SESSION_CONFLICT_DIALOG
      this.$confirm(d.message, d.title, { confirmButtonText: d.confirm, cancelButtonText: d.cancel, type: 'warning' })
        .then(() => this.goActivate())
        .catch(() => {})
    }
  }
}
</script>

<style scoped>
.license-banner {
  /* 粘顶由 App.vue 的 .app-bars 容器负责，授权条与更新条在里面上下排列 */
  display: flex;
  align-items: center;
  justify-content: center;
  flex-wrap: wrap;
  gap: 4px 12px;
  padding: 8px 16px;
  font-size: var(--fs-small);
  line-height: 1.5;
  border-bottom: 1px solid var(--line);
}
.license-banner.is-warning { background: #FBF3DC; color: var(--warn); }
.license-banner.is-danger { background: #F8E5E1; color: var(--seal); }
.license-banner__text { min-width: 0; }
.license-banner__btn {
  flex: none;
  border: 1px solid currentColor;
  border-radius: var(--radius-nav);
  background: transparent;
  color: inherit;
  padding: 2px 10px;
  font-size: var(--fs-small);
  cursor: pointer;
}
.license-banner__btn:disabled { opacity: .6; cursor: default; }
</style>
