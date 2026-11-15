<template>
  <el-button :size="size" :type="type" :icon="copied ? 'el-icon-check' : 'el-icon-document-copy'" @click="copy">
    {{ copied ? copiedLabel : label }}
  </el-button>
</template>

<script>
/** 复制按钮：点击复制 text，按钮短暂显示「已复制」 */
import { copyText } from '@/utils/clipboard'

export default {
  name: 'CopyButton',
  props: {
    text: { type: String, default: '' },
    label: { type: String, default: '复制' },
    copiedLabel: { type: String, default: '已复制' },
    size: { type: String, default: 'small' },
    type: { type: String, default: '' }
  },
  data() { return { copied: false, timer: null } },
  beforeDestroy() { clearTimeout(this.timer) },
  methods: {
    async copy() {
      const ok = await copyText(this.text)
      if (!ok) { this.$message.error('复制失败，请手动选中复制'); return }
      this.copied = true
      clearTimeout(this.timer)
      this.timer = setTimeout(() => { this.copied = false }, 2500)
      this.$emit('copied')
    }
  }
}
</script>
