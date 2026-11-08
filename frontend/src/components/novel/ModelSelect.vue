<template>
  <el-select :value="value" placeholder="默认模型" clearable filterable @change="v => $emit('input', v || '')">
    <el-option-group v-for="g in groups" :key="g.provider" :label="g.label">
      <el-option v-for="opt in g.items" :key="opt.key" :label="opt.label" :value="opt.key"></el-option>
    </el-option-group>
  </el-select>
</template>

<script>
/** 模型下拉（按服务商分组）。groups 来自 options.js 的 loadModelOptions。 */
export default {
  name: 'ModelSelect',
  props: {
    value: { type: String, default: '' },
    groups: { type: Array, default: () => [] }
  }
}
</script>
