<template>
  <div class="prompt-ref-text">
    <template v-for="(t, i) in tokens">
      <span v-if="t.kind === 'ref'" :key="i" class="prompt-ref" :title="t.tip">{{ t.label }}</span>
      <span v-else :key="i">{{ t.text }}</span>
    </template>
  </div>
</template>

<script>
/**
 * 提示词里的图引用高亮：
 * - 链接结构：[名字](refN) 占位 / [名字](attachment://<StoreUri>?type=1) 发送态，chip 直接显示名字
 * - 旧编号（兼容老数据）：@图N / @图片N / 【@图片N】
 * 点击大图仍走下方「用到的资产」卡片，避免编号与资产列表错位误绑。
 */
const REF_RE = /\[([^\]]*)\]\((?:ref\d+|attachment:\/\/[^)]+)\)|【?@图(?:片)?(\d+)】?/g

export default {
  name: 'PromptRefText',
  props: {
    text: { type: String, default: '' },
    assets: { type: Array, default: () => [] }
  },
  computed: {
    tokens() {
      const out = []
      const src = this.text || ''
      let last = 0
      let m
      REF_RE.lastIndex = 0
      while ((m = REF_RE.exec(src))) {
        if (m.index > last) out.push({ text: src.slice(last, m.index) })
        if (m[1] != null) {
          out.push({ kind: 'ref', label: m[1] || '附件', tip: '' })
        } else {
          const no = Number(m[2])
          const a = (this.assets || [])[no - 1]
          out.push({ kind: 'ref', label: `图${no}`, tip: a ? `${a.type}·${a.name}` : '' })
        }
        last = m.index + m[0].length
      }
      if (last < src.length) out.push({ text: src.slice(last) })
      return out
    }
  }
}
</script>

<style scoped>
.prompt-ref-text {
  white-space: pre-wrap;
  word-break: break-all;
}
.prompt-ref {
  display: inline-block;
  padding: 0 6px;
  border: 1px solid var(--line);
  border-radius: var(--radius);
  background: var(--surface);
  color: var(--seal);
  font-size: var(--fs-caption);
  line-height: 1.6;
}
</style>
