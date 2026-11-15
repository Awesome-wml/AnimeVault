<template>
  <el-dialog :title="result ? '签发成功' : '签发授权'" :visible="visible" width="620px" append-to-body
             :close-on-click-modal="false" @update:visible="v => $emit('update:visible', v)" @open="reset" @closed="onClosed">
    <!-- 成功：展示授权码 -->
    <div v-if="result" class="form-stack" data-testid="issue-result">
      <WarnBar v-for="w in result.warnings" :key="w" data-testid="issue-warning">{{ w }}</WarnBar>
      <div class="issued-meta small">
        <span>授权 ID：<b class="mono">{{ result.license.lid }}</b></span>
        <span>套餐：{{ planText }}</span>
        <span>到期：{{ expiresText }}</span>
      </div>
      <LicenseCode :code="result.license.code_display || result.license.code" />
      <p class="note">请把授权码发给用户。授权码可在详情中再次查看。</p>
    </div>

    <!-- 表单 -->
    <el-form v-else ref="form" :model="form" :rules="rules" label-position="top" class="issue-form" @submit.native.prevent>
      <el-form-item label="机器码" prop="machine_code">
        <el-input v-model="form.machine_code" type="textarea" :rows="3" class="mono" placeholder="粘贴用户软件里显示的机器码"
                  data-testid="issue-machine-code" @blur="tidy" />
        <p v-if="check.level !== 'empty'" class="mc-hint" :class="'mc-hint--' + check.level" data-testid="mc-hint">
          {{ check.message }}
        </p>
        <p v-if="check.level === 'ok' || (check.level === 'error' && check.formatted)" class="mc-formatted mono caption">{{ check.formatted }}</p>
      </el-form-item>
      <div class="form-row">
        <el-form-item label="用户邮箱" prop="email">
          <el-input v-model="form.email" placeholder="user@example.com" data-testid="issue-email" />
        </el-form-item>
        <el-form-item label="套餐" prop="plan">
          <el-select v-model="form.plan" placeholder="选择套餐" style="width: 100%" data-testid="issue-plan">
            <el-option v-for="p in plans" :key="p.value" :label="`${p.label}（${p.value}）`" :value="p.value" />
          </el-select>
        </el-form-item>
      </div>
      <el-form-item label="功能点（可多选，也可输入新的功能点后回车）" prop="features">
        <el-select v-model="form.features" multiple filterable allow-create default-first-option placeholder="可选" style="width: 100%">
          <el-option v-for="f in featureOptions" :key="f" :label="f" :value="f" />
        </el-select>
      </el-form-item>
      <div class="form-row">
        <el-form-item label="到期时间" prop="expires">
          <el-date-picker v-model="form.expires" type="date" placeholder="选择日期（含当天）" value-format="timestamp"
                          :picker-options="pickerOptions" style="width: 100%" data-testid="issue-expires" />
        </el-form-item>
        <el-form-item label="设备数上限" prop="dev_max">
          <el-input-number v-model="form.dev_max" :min="1" :max="100" style="width: 100%" data-testid="issue-devmax" />
        </el-form-item>
      </div>
      <el-form-item label="备注" prop="note">
        <el-input v-model="form.note" type="textarea" :rows="2" maxlength="500" show-word-limit placeholder="可选，例如订单号、客户名" />
      </el-form-item>
    </el-form>

    <span slot="footer">
      <template v-if="result">
        <el-button type="primary" data-testid="issue-done" @click="$emit('update:visible', false)">完成</el-button>
      </template>
      <template v-else>
        <el-button @click="$emit('update:visible', false)">取消</el-button>
        <el-button type="primary" :loading="submitting" data-testid="issue-submit" @click="submit">签发</el-button>
      </template>
    </span>
  </el-dialog>
</template>

<script>
import { api } from '@/api'
import { PLANS, FEATURE_OPTIONS, FEATURE_PATTERN, planLabel } from '@/config/plans'
import { precheckMachineCode } from '@/utils/machineCode'
import { endOfDaySeconds, formatTime, isBeforeToday } from '@/utils/time'
import LicenseCode from './LicenseCode.vue'

const blank = () => ({ machine_code: '', email: '', plan: '', features: [], expires: null, dev_max: 1, note: '' })

export default {
  name: 'IssueDialog',
  components: { LicenseCode },
  props: { visible: { type: Boolean, default: false } },
  data() {
    const mcValidator = (rule, value, cb) => {
      const c = precheckMachineCode(value)
      if (c.level === 'empty') return cb(new Error('请粘贴机器码'))
      if (c.level === 'error') return cb(new Error('机器码格式不对：' + c.message))
      cb()
    }
    const featValidator = (rule, value, cb) => {
      const bad = (value || []).filter(f => !FEATURE_PATTERN.test(f))
      bad.length ? cb(new Error('功能点只能是小写字母、数字、下划线：' + bad.join('、'))) : cb()
    }
    const expValidator = (rule, value, cb) => {
      if (!value) return cb(new Error('请选择到期时间'))
      if (isBeforeToday(new Date(value))) return cb(new Error('到期时间不能早于今天'))
      cb()
    }
    return {
      form: blank(), result: null, submitting: false,
      plans: PLANS, featureOptions: FEATURE_OPTIONS,
      pickerOptions: { disabledDate: d => isBeforeToday(d) },
      rules: {
        machine_code: [{ validator: mcValidator, trigger: 'blur' }],
        email: [{ pattern: /^[^\s@]+@[^\s@]+\.[^\s@]+$/, message: '邮箱格式不对', trigger: 'blur' }],
        plan: [{ required: true, message: '请选择套餐', trigger: 'change' }],
        features: [{ validator: featValidator, trigger: 'change' }],
        expires: [{ validator: expValidator, trigger: 'change' }]
      }
    }
  },
  computed: {
    check() { return precheckMachineCode(this.form.machine_code) },
    planText() { return this.result ? planLabel(this.result.license.plan) : '' },
    expiresText() { return this.result ? formatTime(this.result.license.expires_at, false) : '' }
  },
  methods: {
    reset() {
      this.form = blank()
      this.result = null
      this.$nextTick(() => this.$refs.form && this.$refs.form.clearValidate())
    },
    /** 粘贴后整理成带分组的规范格式 */
    tidy() {
      if (this.check.level === 'ok') this.form.machine_code = this.check.formatted
    },
    async submit() {
      const valid = await this.$refs.form.validate().then(() => true, () => false)
      if (!valid) return
      this.submitting = true
      try {
        const f = this.form
        const res = await api.licenses.issue({
          machine_code: this.check.formatted,
          plan: f.plan,
          features: f.features,
          expires_at: endOfDaySeconds(new Date(f.expires)),
          email: f.email.trim() || null,
          dev_max: f.dev_max,
          note: f.note.trim() || null
        })
        this.result = res
        this.$emit('issued', res)
      } catch (e) { /* 拦截器已提示 */ } finally {
        this.submitting = false
      }
    },
    onClosed() { this.result = null }
  }
}
</script>

<style scoped>
.mc-hint { margin-top: 4px; font-size: var(--fs-small); line-height: 1.5; }
.mc-hint--ok { color: var(--ok); }
.mc-hint--error { color: var(--seal); }
.mc-hint--warn { color: var(--warn); }
.mc-formatted { color: var(--ink-muted); word-break: break-all; }
.issued-meta { display: flex; flex-wrap: wrap; gap: 6px 20px; color: var(--ink-muted); }
.issue-form >>> .el-textarea__inner { font-family: var(--font-mono); }
</style>
