<template>
  <div class="page" v-loading="loading">
    <PageHeader title="授权信息" subtitle="本机的授权套餐、到期时间和机器码。" />
    <LicenseInfoCard :status="status" :version="versionText">
      <template #actions>
        <BaseButton variant="primary" :loading="checking" @click="check">立即检查</BaseButton>
        <BaseButton variant="secondary" :loading="checkingUpdate" @click="checkUpdate">检查更新</BaseButton>
        <BaseButton variant="secondary" @click="copy">复制机器码</BaseButton>
        <BaseButton variant="text" @click="remove">清除本机授权</BaseButton>
      </template>
    </LicenseInfoCard>
  </div>
</template>

<script>
import { api } from '@/api'
import { licenseErrorMessage } from '@/api/license'
import LicenseInfoCard from '@/components/license/LicenseInfoCard.vue'
import { licenseGate } from '@/router/licenseGuard'
import { updateGate } from '@/router/updateGate'
import { copyText } from '@/utils/clipboard'
import { confirmDelete } from '@/utils/dialogs'
import { toastError, toastInfo, toastSuccess } from '@/utils/notify'

export default {
  name: 'LicenseInfoSettings',
  components: { LicenseInfoCard },
  data() {
    return { status: {}, loading: false, checking: false, checkingUpdate: false, update: null }
  },
  computed: {
    versionText() {
      const u = this.update
      return u && u.current_version ? `${u.current_version}${u.channel && u.channel !== 'stable' ? `（${u.channel}）` : ''}` : ''
    }
  },
  created() {
    this.load()
    this.loadVersion()
  },
  methods: {
    async load() {
      this.loading = true
      try {
        this.status = await api.license.status()
      } catch (e) {
        toastError(e, '读取授权信息失败')
      } finally {
        this.loading = false
      }
    },
    async loadVersion() {
      try {
        this.update = await api.update.status()
      } catch (_) { /* 版本信息读不到不影响授权信息展示 */ }
    },
    async checkUpdate() {
      if (this.checkingUpdate) return
      this.checkingUpdate = true
      try {
        const s = await api.update.check()
        this.update = s
        updateGate.set(s)
        if (s.check_failed) toastError(null, '检查更新失败，请检查网络后重试')
        else if (s.update_available && s.latest) toastSuccess(`发现新版本 ${s.latest.version}，可在顶部提示条里更新`)
        else toastInfo('已经是最新版本')
      } catch (e) {
        toastError(null, e && e.response && e.response.status === 429 ? '操作太频繁，请稍后再试' : '检查更新失败，请稍后重试')
      } finally {
        this.checkingUpdate = false
      }
    },
    async check() {
      if (this.checking) return
      this.checking = true
      try {
        this.status = await api.license.renewNow()
        licenseGate.set(this.status)
        toastSuccess('授权已更新')
      } catch (e) {
        toastError(null, licenseErrorMessage(e))
        await this.load() // 服务端拒绝时状态已变（如已停用），刷新展示
        licenseGate.invalidate()
      } finally {
        this.checking = false
      }
    },
    async copy() {
      if (!this.status.machine_code) return
      if (await copyText(this.status.machine_code)) toastSuccess('机器码已复制')
      else toastError(null, '复制失败，请手动选中机器码复制')
    },
    async remove() {
      if (!(await confirmDelete('清除后需要重新输入授权码才能继续使用。', '清除本机授权', '清除'))) return
      try {
        await api.license.deactivate()
        licenseGate.invalidate()
        this.$router.replace('/activate')
      } catch (e) {
        toastError(e, '清除授权失败')
      }
    }
  }
}
</script>
