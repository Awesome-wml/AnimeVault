<template>
  <el-dialog append-to-body :title="value.name || '提示词'" :visible="visible" width="680px" @update:visible="v => $emit('update:visible', v)">
    <div class="form-stack">
      <p class="note">提示词在后端 core/prompts/ 文件（system.json、constraints.json）里维护，这里只读展示。</p>
      <FormField v-if="value.system" label="角色身份（system.json）">
        <el-input :value="value.system" type="textarea" :rows="4" readonly label="角色身份" />
      </FormField>
      <FormField v-if="value.contract" label="返回契约（system.json）">
        <el-input :value="value.contract" type="textarea" :rows="8" readonly label="返回契约" />
      </FormField>
      <FormField label="约束（constraints.json）">
        <el-input :value="value.content" type="textarea" :rows="14" readonly label="提示词内容" />
      </FormField>
    </div>
    <template #footer>
      <BaseButton variant="text" @click="$emit('update:visible', false)">关闭</BaseButton>
    </template>
  </el-dialog>
</template>

<script>
/** 提示词查看对话框（只读）。value 为列表里的一行。 */
export default {
  name: 'PromptEditDialog',
  props: {
    visible: Boolean,
    value: { type: Object, default: () => ({}) }
  }
}
</script>
