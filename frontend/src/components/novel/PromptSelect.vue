<template>
  <el-select :value="value" :placeholder="placeholder" clearable @change="v => $emit('input', v || '')">
    <el-option v-for="p in prompts" :key="p._id" :label="p.name" :value="p._id"></el-option>
  </el-select>
</template>

<script>
/** 提示词下拉；不选即用后端默认提示词。 */
export default {
  name: 'PromptSelect',
  props: {
    value: { type: String, default: '' },
    prompts: { type: Array, default: () => [] },
    placeholder: { type: String, default: '默认' }
  }
}
</script>
