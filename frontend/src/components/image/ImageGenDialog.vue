<template>
  <el-dialog append-to-body title="出图设置" :visible="visible" width="480px" @update:visible="v => $emit('update:visible', v)" @open="onOpen">
    <div class="form-stack">
      <FormField label="出图模型" hint="在“设置 → 模型”里新建模型；不选则用账号默认模型。">
        <ModelSelect v-model="draft.model" :groups="groups" placeholder="默认文生图模型" />
      </FormField>
      <FormField v-if="showSheetPrompt && sheetPrompts.length" label="角色三视图提示词" hint="在“设置 → 提示词”里新建“角色三视图”类型；不选则用内置模板。">
        <PromptSelect v-model="draft.sheetPrompt" :prompts="sheetPrompts" placeholder="内置模板" />
      </FormField>
      <p class="note">只对本作品生效，记在这台电脑的浏览器里。角色设定板按横版出图，道具、场景按方形，分镜画面按横版，尺寸随所选模型自动取合规值。</p>
    </div>
    <template #footer>
      <BaseButton variant="text" @click="$emit('update:visible', false)">取消</BaseButton>
      <BaseButton @click="save">保存</BaseButton>
    </template>
  </el-dialog>
</template>

<script>
/**
 * 出图设置对话框（资产页、分镜页的“更多 → 出图设置”）。
 * v-model 风格：value 为 { model, sheetPrompt }，保存时 emit('input', 新值)。
 * groups 来自 loadModelOptions()（全部模型），sheetPrompts 来自 loadPrompts().sheet。
 */
import ModelSelect from '@/components/novel/ModelSelect.vue'
import PromptSelect from '@/components/novel/PromptSelect.vue'

export default {
  name: 'ImageGenDialog',
  components: { ModelSelect, PromptSelect },
  props: {
    visible: Boolean,
    value: { type: Object, required: true },
    groups: { type: Array, default: () => [] },
    sheetPrompts: { type: Array, default: () => [] },
    showSheetPrompt: Boolean
  },
  data() {
    return { draft: { model: '', sheetPrompt: '' } }
  },
  methods: {
    onOpen() { this.draft = { ...this.value } },
    save() {
      this.$emit('input', { ...this.draft })
      this.$emit('update:visible', false)
    }
  }
}
</script>
