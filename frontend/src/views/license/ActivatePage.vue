<template>
  <CenterLayout>
    <template v-if="!activated">
      <PageHeader title="激活 DongAI" subtitle="首次使用需要授权：把下面的机器码发给我们，拿到授权码后粘贴到下方即可。" />

      <MachineCodeCard :groups="groups" :loading="loadingCode" :error="codeError" />

      <form class="form-stack" novalidate @submit.prevent="submit">
        <LicenseCodeInput v-model="code" :error="error" :disabled="loading" />
        <div>
          <BaseButton type="submit" variant="primary" size="lg" :loading="loading" :disabled="!code.trim()">激活</BaseButton>
        </div>
      </form>
    </template>

    <template v-else>
      <PageHeader title="激活成功" subtitle="授权已生效，可以开始使用了。" />
      <LicenseInfoCard :status="result">
        <template #actions>
          <BaseButton variant="primary" size="lg" @click="enter">进入工作台</BaseButton>
        </template>
      </LicenseInfoCard>
    </template>
  </CenterLayout>
</template>

<script>
/** 激活页：只负责组装（机器码卡 + 授权码输入 + 结果卡），接口全部走 api.license。 */
import { api } from '@/api'
import { licenseErrorMessage } from '@/api/license'
import CenterLayout from '@/layouts/CenterLayout.vue'
import MachineCodeCard from '@/components/license/MachineCodeCard.vue'
import LicenseCodeInput from '@/components/license/LicenseCodeInput.vue'
import LicenseInfoCard from '@/components/license/LicenseInfoCard.vue'
import { licenseGate } from '@/router/licenseGuard'
import { HOME_PATH } from '@/utils/licenseGate'

export default {
  name: 'ActivatePage',
  components: { CenterLayout, MachineCodeCard, LicenseCodeInput, LicenseInfoCard },
  data() {
    return { groups: [], loadingCode: true, codeError: '', code: '', error: '', loading: false, activated: false, result: {} }
  },
  watch: {
    // 输入变化时清掉上一次的错误提示
    code() { this.error = '' }
  },
  created() {
    this.loadMachineCode()
  },
  methods: {
    async loadMachineCode() {
      this.loadingCode = true
      try {
        const res = await api.license.machineCode()
        this.groups = res.groups || []
      } catch (e) {
        this.codeError = licenseErrorMessage(e)
      } finally {
        this.loadingCode = false
      }
    },
    async submit() {
      if (this.loading || !this.code.trim()) return
      this.loading = true
      this.error = ''
      try {
        this.result = await api.license.activate(this.code)
        this.activated = true
      } catch (e) {
        this.error = licenseErrorMessage(e)
      } finally {
        this.loading = false
      }
    },
    enter() {
      // 此时才写入状态：激活成功卡片展示期间，守卫不会把用户提前踢走
      licenseGate.set(this.result)
      const redirect = this.$route.query.redirect
      this.$router.replace(typeof redirect === 'string' && redirect.startsWith('/') ? redirect : HOME_PATH)
    }
  }
}
</script>
