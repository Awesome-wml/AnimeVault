<template>
  <el-dialog :title="`AI 提取${conf.label}`" :visible="visible" width="640px" @update:visible="v => $emit('update:visible', v)" @open="text = novel">
    <div class="form-stack">
      <FormField label="小说文本" :hint="conf.extractHint">
        <el-input v-model="text" type="textarea" :autosize="{ minRows: 10, maxRows: 18 }" placeholder="默认使用小说页的全文，也可以只粘贴一段" />
      </FormField>
      <el-checkbox v-model="useStyle">按项目风格提取{{ styleName ? `（${styleName}）` : '' }}</el-checkbox>
    </div>
    <template #footer>
      <BaseButton @click="$emit('update:visible', false)">取消</BaseButton>
      <BaseButton variant="primary" :loading="extracting" @click="extract">提取</BaseButton>
    </template>
  </el-dialog>
</template>

<script>
/** AI 从小说文本提取一类资产。成功 emit('done')。 */
import { assetKind } from './kinds'
import { runAction, toastWarning } from '@/utils/notify'

export default {
  name: 'ExtractDialog',
  props: {
    visible: Boolean,
    kind: { type: String, required: true },
    projectId: { type: String, required: true },
    novel: { type: String, default: '' },
    styleId: { type: String, default: '' },
    styleName: { type: String, default: '' }
  },
  data() {
    return { text: '', useStyle: true, extracting: false }
  },
  computed: {
    conf() { return assetKind(this.kind) }
  },
  methods: {
    async extract() {
      if (!this.text.trim()) { toastWarning('请先粘贴小说文本'); return }
      this.extracting = true
      const ok = await runAction(
        () => this.conf.api.extract({
          project_id: this.projectId,
          novel_text: this.text,
          style: this.useStyle ? this.styleId : ''
        }),
        { success: res => (res && res.message) || '提取完成', error: '提取失败' }
      )
      this.extracting = false
      if (ok) {
        this.$emit('update:visible', false)
        this.$emit('done')
      }
    }
  }
}
</script>
