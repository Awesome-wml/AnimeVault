<template>
  <div class="lic-code">
    <pre class="lic-code__pre mono" :class="{ 'lic-code__pre--folded': folded }" data-testid="license-code">{{ shown }}</pre>
    <div class="inline-actions">
      <el-button v-if="foldable" type="text" size="small" data-testid="toggle-code" @click="folded = !folded">
        {{ folded ? '展开完整授权码' : '收起' }}
      </el-button>
      <CopyButton :text="code" label="复制授权码" copied-label="已复制" type="primary" data-testid="copy-code" />
    </div>
  </div>
</template>

<script>
/** 授权码展示：code_display 格式，等宽多行，可折叠，可复制。复制的是展示格式（客户端粘贴时会自动去掉空白和短横线）。 */
export default {
  name: 'LicenseCode',
  props: {
    code: { type: String, default: '' },
    foldable: { type: Boolean, default: false }
  },
  data() { return { folded: this.foldable } },
  computed: {
    shown() {
      if (!this.code) return '（无）'
      if (!this.folded) return this.code
      const lines = this.code.split('\n')
      return lines.slice(0, 1).join('\n') + (lines.length > 1 ? '\n……（共 ' + lines.length + ' 行，点击展开）' : '')
    }
  }
}
</script>

<style scoped>
.lic-code { display: flex; flex-direction: column; gap: 8px; }
.lic-code__pre {
  margin: 0; padding: 12px 14px; background: var(--side); border: 1px solid var(--line); border-radius: var(--radius);
  font-size: 13px; line-height: 1.7; white-space: pre-wrap; word-break: break-all; user-select: all;
}
</style>
