<template>
  <div class="views-editor">
    <div v-for="(v, i) in value" :key="i" class="views-editor__item">
      <el-input :value="v.name" size="small" placeholder="视角名，如 门口视角" maxlength="20" :aria-label="`视角 ${i + 1} 名称`" @input="x => patch(i, 'name', x)" />
      <el-input :value="v.camera" size="small" placeholder="机位朝向，30 字内，如 站在门口朝屋内" :maxlength="30" :aria-label="`视角 ${i + 1} 机位朝向`" @input="x => patch(i, 'camera', x)" />
      <BaseButton v-if="value.length > 1" variant="text" :aria-label="`删除视角 ${i + 1}`" @click="remove(i)">删除</BaseButton>
    </div>
    <BaseButton variant="text" strong @click="add">+ 添加视角</BaseButton>
  </div>
</template>

<script>
/** 表单弹窗里的视角列表编辑：名称 + 机位朝向。v-model 是 viewDrafts() 产出的草稿数组，保存前用 cleanViews() 整理。 */
export default {
  name: 'SceneViewsEditor',
  props: {
    value: { type: Array, default: () => [] }
  },
  methods: {
    patch(i, key, v) {
      this.$emit('input', this.value.map((x, j) => (j === i ? { ...x, [key]: v } : x)))
    },
    add() {
      this.$emit('input', [...this.value, { name: '', camera: '', image_path: null }])
    },
    remove(i) {
      this.$emit('input', this.value.filter((_, j) => j !== i))
    }
  }
}
</script>

<style scoped>
.views-editor { display: flex; flex-direction: column; gap: 8px; }
.views-editor__item { display: grid; grid-template-columns: 1fr 1.6fr auto; gap: 6px; align-items: center; }
</style>
