<template>
  <el-dialog append-to-body :title="title" :visible="visible" width="680px" @update:visible="v => $emit('update:visible', v)">
    <div class="form-stack">
      <p v-if="form.is_builtin" class="note prompt-edit__desc">
        {{ form.description || '系统内置提示词，随代码更新。' }}
        修改后保存会覆盖内置内容；想换回代码版本用列表里的“恢复内置”，想另存一份用“复制为自定义”。
      </p>
      <FormField label="名称" required>
        <el-input v-model="form.name" :disabled="form.is_builtin" />
      </FormField>
      <div class="prompts__row">
        <FormField label="类型" required>
          <el-select v-model="form.type" placeholder="选择类型" :disabled="form.is_builtin">
            <el-option v-for="t in types" :key="t.value" :label="t.label" :value="t.value" />
          </el-select>
        </FormField>
        <FormField label="题材分类">
          <el-select v-model="form.category" filterable allow-create default-first-option :disabled="form.is_builtin">
            <el-option v-for="c in categoryOptions" :key="c" :label="c" :value="c" />
          </el-select>
        </FormField>
        <FormField label="版本">
          <el-input v-model="form.version" placeholder="v1.0" :disabled="form.is_builtin" />
        </FormField>
      </div>
      <FormField label="内容" required>
        <el-input v-model="form.content" type="textarea" :rows="14" label="提示词内容" />
      </FormField>
    </div>
    <template #footer>
      <BaseButton variant="text" @click="$emit('update:visible', false)">取消</BaseButton>
      <BaseButton variant="primary" :loading="saving" @click="submit">保存</BaseButton>
    </template>
  </el-dialog>
</template>

<script>
/**
 * 提示词编辑对话框。value 为要编辑的记录（新建时为 newPromptDraft()），内部复制一份编辑，保存时 emit('save', form)。
 * 内置提示词只允许改内容：名称、类型、题材、版本禁用，顶部显示该环节用途与可用占位符（description）。
 */
import { validatePrompt } from './prompt-state'

export default {
  name: 'PromptEditDialog',
  props: {
    visible: Boolean,
    value: { type: Object, default: () => ({}) },
    types: { type: Array, default: () => [] },
    categoryOptions: { type: Array, default: () => ['通用'] },
    saving: Boolean
  },
  data() {
    return { form: { ...this.value } }
  },
  computed: {
    title() {
      if (this.form.is_builtin) return '查看 / 编辑内置提示词'
      return this.form._id ? '编辑提示词' : '新建提示词'
    }
  },
  watch: {
    value(v) { this.form = { ...v } },
    visible(v) { if (v) this.form = { ...this.value } }
  },
  methods: {
    submit() {
      const err = validatePrompt(this.form)
      if (err) {
        this.$message.warning(err)
        return
      }
      this.$emit('save', { ...this.form })
    }
  }
}
</script>

<style scoped>
.prompts__row { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 16px; }
.prompt-edit__desc { margin: 0; line-height: 1.6; }
</style>
