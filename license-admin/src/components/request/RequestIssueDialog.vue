<template>
  <el-dialog :title="result ? '签发成功' : '签发申请单'" :visible="visible" width="620px" append-to-body
             :close-on-click-modal="false" @update:visible="v => $emit('update:visible', v)" @open="reset" @closed="result = null">
    <!-- 成功：展示授权码，可复制 -->
    <div v-if="result" class="form-stack" data-testid="request-issue-result">
      <WarnBar v-for="w in result.warnings" :key="w" data-testid="request-issue-warning">{{ w }}</WarnBar>
      <div class="issued-meta small">
        <span>授权 ID：<b class="mono" data-testid="request-issued-lid">{{ result.license.lid }}</b></span>
        <span>邮箱：{{ result.license.email || '-' }}</span>
        <span>到期：{{ expiresText }}</span>
      </div>
      <LicenseCode :code="result.license.code_display || result.license.code" />
      <p class="note">请把授权码发给用户（邮箱 {{ request && request.email }}）。授权码可在授权详情中再次查看。</p>
    </div>

    <el-form v-else-if="request" ref="form" :model="form" :rules="rules" label-position="top" @submit.native.prevent>
      <el-form-item label="用户邮箱（来自申请单）">
        <el-input :value="request.email" readonly data-testid="request-issue-email" />
      </el-form-item>
      <el-form-item :label="`机器码（来自申请单，${request.components_count} 个分量）`">
        <el-input :value="request.machine_code" type="textarea" :rows="3" readonly class="mono" data-testid="request-issue-mc" />
      </el-form-item>
      <LicenseTermsFields v-model="form" prefix="request-issue" />
    </el-form>

    <span slot="footer">
      <template v-if="result">
        <el-button type="primary" data-testid="request-issue-done" @click="$emit('update:visible', false)">完成</el-button>
      </template>
      <template v-else>
        <el-button @click="$emit('update:visible', false)">取消</el-button>
        <el-button type="primary" :loading="submitting" data-testid="request-issue-submit" @click="submit">签发</el-button>
      </template>
    </span>
  </el-dialog>
</template>

<script>
import { api } from '@/api'
import { endOfDaySeconds, formatTime } from '@/utils/time'
import { licenseTermsRules } from '@/utils/validators'
import LicenseCode from '@/components/license/LicenseCode.vue'
import LicenseTermsFields from '@/components/license/LicenseTermsFields.vue'

const blank = (note = '') => ({ plan: '', features: [], expires: null, dev_max: 1, note })

/** 申请单「签发」弹窗：邮箱和机器码取自申请单（只读），管理员选套餐、到期、功能点；成功后显示授权码并可复制。 */
export default {
  name: 'RequestIssueDialog',
  components: { LicenseCode, LicenseTermsFields },
  props: {
    visible: { type: Boolean, default: false },
    request: { type: Object, default: null }
  },
  data() {
    return {
      form: blank(), result: null, submitting: false,
      rules: licenseTermsRules(() => this.$store.getters.featurePattern)
    }
  },
  computed: {
    expiresText() { return this.result ? formatTime(this.result.license.expires_at, false) : '' }
  },
  methods: {
    reset() {
      this.form = blank(this.request && this.request.note ? this.request.note : '')
      this.result = null
      this.$nextTick(() => this.$refs.form && this.$refs.form.clearValidate())
    },
    async submit() {
      const valid = await this.$refs.form.validate().then(() => true, () => false)
      if (!valid) return
      this.submitting = true
      try {
        const f = this.form
        const res = await api.requests.issue(this.request.id, {
          plan: f.plan, features: f.features, expires_at: endOfDaySeconds(new Date(f.expires)),
          dev_max: f.dev_max, note: (f.note || '').trim() || null
        })
        this.result = res
        this.$emit('issued', res)
      } catch (e) {
        // 拦截器已提示；申请单已被别人处理时通知页面刷新
        if (e.code === 'REQUEST_NOT_PENDING' || e.code === 'REQUEST_NOT_FOUND') { this.$emit('update:visible', false); this.$emit('stale') }
      } finally {
        this.submitting = false
      }
    }
  }
}
</script>

<style scoped>
.issued-meta { display: flex; flex-wrap: wrap; gap: 6px 20px; color: var(--ink-muted); }
</style>
