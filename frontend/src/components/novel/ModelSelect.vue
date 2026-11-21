<template>
  <el-select :value="value" :placeholder="placeholder" clearable filterable @change="v => $emit('input', v || '')">
    <el-option-group v-for="g in groups" :key="g.id || g.label" :label="g.label">
      <el-option v-for="opt in g.items" :key="opt.key" :label="opt.label" :value="opt.key" :disabled="!!opt.disabled"></el-option>
    </el-option-group>
  </el-select>
</template>

<script>
/** 模型下拉（一条预设一组）。groups 来自 options.js 的 loadModelOptions；没配密钥的预设整组置灰。 */
export default {
  name: 'ModelSelect',
  props: {
    value: { type: String, default: '' },
    groups: { type: Array, default: () => [] },
    placeholder: { type: String, default: '默认模型' }
  }
}
</script>
