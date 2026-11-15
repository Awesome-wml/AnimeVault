<template>
  <div class="page" v-loading="loading">
    <PageHeader title="授权信息" subtitle="本机的授权套餐、到期时间和机器码。" />
    <LicenseInfoCard :status="status">
      <template #actions>
        <BaseButton variant="secondary" @click="copy">复制机器码</BaseButton>
        <BaseButton variant="text" @click="remove">清除本机授权</BaseButton>
      </template>
    </LicenseInfoCard>
  </div>
</template>

<script>
import { api } from '@/api'
import LicenseInfoCard from '@/components/license/LicenseInfoCard.vue'
import { licenseGate } from '@/router/licenseGuard'
import { copyText } from '@/utils/clipboard'
import { confirmDelete } from '@/utils/dialogs'
import { toastError, toastSuccess } from '@/utils/notify'

export default {
  name: 'LicenseInfoSettings',
  components: { LicenseInfoCard },
  data() {
    return { status: {}, loading: false }
  },
  created() {
    this.load()
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
