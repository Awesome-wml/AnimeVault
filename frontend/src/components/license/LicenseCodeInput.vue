<template>
  <FormField label="授权码" :error="error" hint="支持直接粘贴带换行和短横线的授权码。">
    <el-input
      type="textarea"
      :rows="6"
      :value="value"
      :disabled="disabled"
      resize="none"
      class="license-input"
      placeholder="在这里粘贴我们发给你的授权码"
      spellcheck="false"
      autocomplete="off"
      @input="$emit('input', $event)"
    />
  </FormField>
</template>

<script>
/** 授权码输入框（v-model）：多行，等宽字体；规范化由后端 normalize_input 完成，这里原样传。 */
export default {
  name: 'LicenseCodeInput',
  props: {
    value: { type: String, default: '' },
    error: { type: String, default: '' },
    disabled: Boolean
  }
}
</script>

<style scoped>
.license-input >>> .el-textarea__inner {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 13px;
  line-height: 1.6;
  word-break: break-all;
}
</style>
