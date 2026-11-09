<template>
  <el-dialog title="润色结果" :visible="visible" width="760px" @update:visible="v => $emit('update:visible', v)" @open="draft = text">
    <div class="form-stack">
      <p class="note">原文 {{ sourceLength }} 字 → 润色后 {{ draft.length }} 字。确认后替换正文并保存；可以先在下面改一改。</p>
      <el-input v-model="draft" type="textarea" :autosize="{ minRows: 14, maxRows: 24 }" label="润色结果" />
    </div>
    <template #footer>
      <BaseButton @click="$emit('update:visible', false)">放弃</BaseButton>
      <BaseButton variant="primary" :disabled="!draft.trim()" @click="confirm">替换正文</BaseButton>
    </template>
  </el-dialog>
</template>

<script>
/** 展示润色结果，用户确认后 emit('confirm', 文本)。 */
export default {
  name: 'PolishDialog',
  props: {
    visible: Boolean,
    text: { type: String, default: '' },
    sourceLength: { type: Number, default: 0 }
  },
  data() {
    return { draft: '' }
  },
  methods: {
    confirm() {
      this.$emit('confirm', this.draft)
      this.$emit('update:visible', false)
    }
  }
}
</script>
