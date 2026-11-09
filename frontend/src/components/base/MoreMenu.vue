<template>
  <el-dropdown trigger="click" placement="bottom-end" @command="onCommand">
    <BaseButton variant="text" :aria-label="label">{{ text }}</BaseButton>
    <el-dropdown-menu slot="dropdown">
      <el-dropdown-item
        v-for="item in items"
        :key="item.command"
        :command="item.command"
        :disabled="item.disabled"
        :class="{ 'dropdown-item--danger': item.danger }"
      >{{ item.label }}</el-dropdown-item>
    </el-dropdown-menu>
  </el-dropdown>
</template>

<script>
/**
 * “更多”菜单：把次要操作收起来，卡片/行上只留一个主操作。
 * items: [{ command, label, danger?, disabled? }]，选中后 emit('command', command)。
 */
import BaseButton from './BaseButton.vue'

export default {
  name: 'MoreMenu',
  components: { BaseButton },
  props: {
    items: { type: Array, required: true },
    text: { type: String, default: '更多' },
    label: { type: String, default: '更多操作' }
  },
  methods: {
    onCommand(cmd) { this.$emit('command', cmd) }
  }
}
</script>
