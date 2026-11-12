<template>
  <el-dialog title="变装 · 新增穿搭形态" :visible="visible" width="520px" @update:visible="v => $emit('update:visible', v)" @open="reset">
    <div class="form-stack">
      <FormField label="形态名" required hint="如 换上锦衣形态、受伤狼狈形态">
        <el-input v-model.trim="name" maxlength="20" placeholder="形态名" :aria-label="`${(item && item.name) || ''} 形态名`" />
      </FormField>
      <FormField label="穿搭" required hint="从头到脚：发饰、上衣、外套、下装、鞋袜、配饰、随身小件">
        <el-input v-model="outfit" type="textarea" :autosize="{ minRows: 3, maxRows: 6 }" placeholder="枯黄乱发半束以木簪，粗麻布短褂……" :aria-label="`${(item && item.name) || ''} 穿搭`" />
      </FormField>
      <FormField label="出现场次" hint="可选，剧本场次号，如 1、3、5">
        <el-input v-model.trim="sceneNos" maxlength="20" placeholder="1、3、5" :aria-label="`${(item && item.name) || ''} 出现场次`" />
      </FormField>
    </div>
    <template #footer>
      <BaseButton @click="$emit('update:visible', false)">取消</BaseButton>
      <BaseButton variant="primary" :loading="saving" @click="submit">保存变装</BaseButton>
    </template>
  </el-dialog>
</template>

<script>
/**
 * 变装弹窗：给当前角色追加一套穿搭形态（名称 + 穿搭 + 可选场次）。
 * 只收集草稿，提交由页面层调 character.update 整份 forms 落库；saving 由页面控制。
 */
import { characterForms } from './forms'
import { toastWarning } from '@/utils/notify'

export default {
  name: 'OutfitDialog',
  props: {
    visible: Boolean,
    item: { type: Object, default: null },
    saving: Boolean
  },
  data() {
    return { name: '', outfit: '', sceneNos: '' }
  },
  methods: {
    reset() {
      const n = this.item ? characterForms(this.item).length : 1
      this.name = `形态${n + 1}`
      this.outfit = ''
      this.sceneNos = ''
    },
    submit() {
      if (!this.outfit) { toastWarning('请填写这套穿搭'); return }
      this.$emit('submit', { name: this.name, outfit: this.outfit, scene_nos: this.sceneNos })
    }
  }
}
</script>
