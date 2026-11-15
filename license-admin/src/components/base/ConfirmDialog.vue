<template>
  <el-dialog :title="title" :visible="visible" width="460px" append-to-body :close-on-click-modal="false"
             @update:visible="v => $emit('update:visible', v)" @open="input = ''">
    <div class="confirm">
      <p class="confirm__msg" :class="{ 'confirm__msg--danger': danger }"><slot>{{ message }}</slot></p>
      <div v-if="requireText" class="confirm__type">
        <p class="note">请输入 <code class="mono confirm__target">{{ requireText }}</code> 以确认</p>
        <el-input v-model="input" :placeholder="requireText" autocomplete="off" data-testid="confirm-input" />
      </div>
    </div>
    <span slot="footer">
      <el-button @click="$emit('update:visible', false)">取消</el-button>
      <el-button :type="danger ? 'danger' : 'primary'" :loading="loading" :disabled="!matched"
                 data-testid="confirm-ok" @click="$emit('confirm')">{{ confirmLabel }}</el-button>
    </span>
  </el-dialog>
</template>

<script>
/** 确认弹窗。传 requireText 时必须原样输入该文本才能确认（用于吊销这类不可恢复操作）。 */
export default {
  name: 'ConfirmDialog',
  props: {
    visible: { type: Boolean, default: false },
    title: { type: String, default: '请确认' },
    message: { type: String, default: '' },
    confirmLabel: { type: String, default: '确认' },
    danger: { type: Boolean, default: false },
    requireText: { type: String, default: '' },
    loading: { type: Boolean, default: false }
  },
  data() { return { input: '' } },
  computed: {
    matched() { return !this.requireText || this.input.trim() === this.requireText }
  }
}
</script>

<style scoped>
.confirm { display: flex; flex-direction: column; gap: 14px; }
.confirm__msg { line-height: 1.7; }
.confirm__msg--danger { color: var(--seal); }
.confirm__type { display: flex; flex-direction: column; gap: 6px; }
.confirm__target { background: var(--side); padding: 0 6px; border-radius: 4px; }
</style>
