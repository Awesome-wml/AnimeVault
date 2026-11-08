<template>
  <el-dialog :title="title" :visible="visible" width="520px" @update:visible="v => $emit('update:visible', v)" @open="reset">
    <div class="form-stack">
      <FormField label="名称" required>
        <el-input v-model.trim="form.name" :placeholder="`${conf.label}名称`" maxlength="40" />
      </FormField>
      <FormField v-if="conf.typeField" label="类型">
        <el-input v-model.trim="form.type" :placeholder="conf.typePlaceholder" maxlength="20" />
      </FormField>
      <FormField :label="conf.descLabel">
        <el-input v-model="form.description" type="textarea" :autosize="{ minRows: 4, maxRows: 10 }" :placeholder="conf.descPlaceholder" />
      </FormField>
      <FormField v-if="conf.hasVoice" label="音色">
        <el-select v-model="form.voice_name" placeholder="选择音色" filterable clearable>
          <el-option v-for="v in voices" :key="v.name" :label="voiceOptionLabel(v)" :value="v.name"></el-option>
        </el-select>
      </FormField>
    </div>
    <template #footer>
      <BaseButton @click="$emit('update:visible', false)">取消</BaseButton>
      <BaseButton variant="primary" :loading="saving" @click="save">保存</BaseButton>
    </template>
  </el-dialog>
</template>

<script>
/** 新建 / 编辑一个资产。item 为空时新建。保存成功 emit('saved')。 */
import { assetKind } from './kinds'
import { voiceOptionLabel } from '@/components/voice/voices'
import { runAction, toastWarning } from '@/utils/notify'

export default {
  name: 'AssetFormDialog',
  props: {
    visible: Boolean,
    kind: { type: String, required: true },
    projectId: { type: String, required: true },
    item: { type: Object, default: null },
    voices: { type: Array, default: () => [] }
  },
  data() {
    return { saving: false, form: { name: '', type: '', description: '', voice_name: '' } }
  },
  computed: {
    conf() { return assetKind(this.kind) },
    title() { return this.item ? `编辑${this.conf.label}` : `添加${this.conf.label}` }
  },
  methods: {
    voiceOptionLabel,
    reset() {
      const it = this.item || {}
      this.form = {
        name: it.name || '',
        type: (this.conf.typeField && it[this.conf.typeField]) || '',
        description: it.description || '',
        voice_name: it.voice_name || ''
      }
    },
    payload() {
      const data = { name: this.form.name, description: this.form.description }
      if (this.conf.typeField) data[this.conf.typeField] = this.form.type
      if (this.conf.hasVoice && this.form.voice_name) data.voice_name = this.form.voice_name
      return data
    },
    async save() {
      if (!this.form.name) { toastWarning('请填写名称'); return }
      this.saving = true
      const ok = await runAction(
        () => (this.item
          ? this.conf.api.update(this.item.id, this.payload())
          : this.conf.api.create({ project_id: this.projectId, ...this.payload() })),
        { success: this.item ? '已保存' : '已添加', error: '保存失败' }
      )
      this.saving = false
      if (ok) {
        this.$emit('update:visible', false)
        this.$emit('saved')
      }
    }
  }
}
</script>
