<template>
  <div class="terms">
    <div class="form-row">
      <el-form-item label="套餐" prop="plan">
        <el-select :value="value.plan" placeholder="选择套餐" style="width: 100%" :data-testid="prefix + '-plan'" @input="set('plan', $event)">
          <el-option v-for="p in plans" :key="p.value" :label="`${p.label}（${p.value}）`" :value="p.value" />
        </el-select>
      </el-form-item>
      <el-form-item label="到期时间" prop="expires">
        <el-date-picker :value="value.expires" type="date" placeholder="选择日期（含当天）" value-format="timestamp"
                        :picker-options="pickerOptions" style="width: 100%" :data-testid="prefix + '-expires'"
                        @input="set('expires', $event)" />
      </el-form-item>
    </div>
    <el-form-item label="功能点（可多选，也可输入新的功能点后回车）" prop="features">
      <el-select :value="value.features" multiple filterable allow-create default-first-option placeholder="可选" style="width: 100%"
                 :data-testid="prefix + '-features'" @input="set('features', $event)">
        <el-option v-for="f in featureOptions" :key="f" :label="f" :value="f" />
      </el-select>
    </el-form-item>
    <el-form-item label="设备数上限" prop="dev_max">
      <el-input-number :value="value.dev_max" :min="devMax.min" :max="devMax.max" style="width: 100%"
                       :data-testid="prefix + '-devmax'" @input="set('dev_max', $event)" />
    </el-form-item>
    <el-form-item label="备注" prop="note">
      <el-input :value="value.note" type="textarea" :rows="2" maxlength="500" show-word-limit placeholder="可选，例如订单号、客户名"
                @input="set('note', $event)" />
    </el-form-item>
  </div>
</template>

<script>
import { isBeforeToday } from '@/utils/time'

/**
 * 授权条款字段（套餐、到期、功能点、设备数、备注），签发和申请单签发共用。
 * 必须放在父级 el-form 里（prop 同名）；校验规则见 utils/validators 的 licenseTermsRules。
 * v-model 绑定 {plan, expires, features, dev_max, note}；套餐和功能点候选来自 store（服务端 /meta，失败时用兜底常量）。
 */
export default {
  name: 'LicenseTermsFields',
  props: {
    value: { type: Object, required: true },
    prefix: { type: String, default: 'issue' }
  },
  data() { return { pickerOptions: { disabledDate: d => isBeforeToday(d) } } },
  computed: {
    plans() { return this.$store.getters.planOptions },
    featureOptions() { return this.$store.getters.featureOptions },
    devMax() { return this.$store.getters.devMax }
  },
  methods: {
    set(key, v) { this.$emit('input', { ...this.value, [key]: v }) }
  }
}
</script>
