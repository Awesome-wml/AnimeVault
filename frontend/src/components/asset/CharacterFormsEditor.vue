<template>
  <div class="forms-editor">
    <div v-for="(f, i) in value" :key="i" class="forms-editor__item">
      <div class="forms-editor__head">
        <el-input :value="f.name" size="small" placeholder="形态名，如 上门索财形态" maxlength="20" :aria-label="`形态 ${i + 1} 名称`" @input="v => patch(i, 'name', v)" />
        <el-input :value="f.scene_nos" size="small" placeholder="用在剧本第几场，如 1、3、10-20" :aria-label="`形态 ${i + 1} 出现场次`" @input="v => patch(i, 'scene_nos', v)" />
        <BaseButton v-if="value.length > 1" variant="text" :aria-label="`删除形态 ${i + 1}`" @click="remove(i)">删除</BaseButton>
      </div>
      <el-input :value="f.outfit" type="textarea" :autosize="{ minRows: 2, maxRows: 6 }" placeholder="从头到脚穿搭：发饰、上衣、外套、下装、鞋袜、配饰、随身小件" :aria-label="`形态 ${i + 1} 穿搭`" @input="v => patch(i, 'outfit', v)" />
    </div>
    <BaseButton variant="text" strong @click="add">+ 添加形态</BaseButton>
  </div>
</template>

<script>
/**
 * 表单弹窗里的形态列表编辑：每个形态 = 名称 + 出现场次（文本，保存时转数组）+ 穿搭。
 * v-model 是 formDrafts() 产出的草稿数组；保存前由页面 / 弹窗用 cleanForms() 整理。
 */
export default {
  name: 'CharacterFormsEditor',
  props: {
    value: { type: Array, default: () => [] }
  },
  methods: {
    patch(i, key, v) {
      const next = this.value.map((f, j) => (j === i ? { ...f, [key]: v } : f))
      this.$emit('input', next)
    },
    add() {
      this.$emit('input', [...this.value, { name: '', outfit: '', scene_nos: '', image_path: null }])
    },
    remove(i) {
      this.$emit('input', this.value.filter((_, j) => j !== i))
    }
  }
}
</script>

<style scoped>
.forms-editor { display: flex; flex-direction: column; gap: 12px; }
.forms-editor__item { display: flex; flex-direction: column; gap: 6px; padding: 10px; border: 1px solid var(--line); border-radius: var(--radius); }
.forms-editor__head { display: grid; grid-template-columns: 1fr 1fr auto; gap: 6px; align-items: center; }
</style>
