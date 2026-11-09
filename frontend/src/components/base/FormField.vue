<template>
  <label class="form-field" :class="{ 'is-error': !!error }">
    <span class="form-field__label">{{ label }}<span v-if="required" class="form-field__req" aria-hidden="true"> *</span></span>
    <slot></slot>
    <span v-if="error" class="form-field__error" role="alert">{{ error }}</span>
    <span v-else-if="hint" class="form-field__hint">{{ hint }}</span>
  </label>
</template>

<script>
/**
 * 表单项：上方灰色小标签 + 控件 + 提示/错误。
 * 控件用 el-input / el-select 等（外观由 styles/element-theme.css 统一）。
 */
export default {
  name: 'FormField',
  props: {
    label: { type: String, required: true },
    hint: { type: String, default: '' },
    error: { type: String, default: '' },
    required: Boolean
  }
}
</script>

<style scoped>
.form-field { display: flex; flex-direction: column; gap: 4px; font-size: var(--fs-small); color: var(--ink-muted); }
.form-field__req { color: var(--seal); }
.form-field__hint { font-size: var(--fs-caption); color: var(--ink-muted); }
.form-field__error { font-size: var(--fs-caption); color: var(--seal); }
.form-field >>> .el-select { width: 100%; }
.form-field.is-error >>> .el-input__inner,
.form-field.is-error >>> .el-textarea__inner { border-color: var(--seal); }
</style>
