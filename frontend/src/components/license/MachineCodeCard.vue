<template>
  <section class="machine-code" aria-label="本机机器码">
    <h2 class="machine-code__title">本机机器码</h2>
    <p class="machine-code__tip">把机器码发给我们，我们会给你授权码。</p>
    <div class="machine-code__box" :class="{ 'is-empty': !groups.length }">
      <template v-if="groups.length">
        <span v-for="(g, i) in groups" :key="i" class="machine-code__group">{{ g }}</span>
      </template>
      <span v-else class="machine-code__placeholder">{{ loading ? '读取中…' : (error || '暂时无法获取机器码') }}</span>
    </div>
    <BaseButton variant="secondary" :disabled="!groups.length" @click="copy">复制机器码</BaseButton>
  </section>
</template>

<script>
/** 机器码展示卡：分组显示 + 复制按钮。数据由页面传入，本组件不请求接口。 */
import { copyText } from '@/utils/clipboard'
import { toastError, toastSuccess } from '@/utils/notify'

export default {
  name: 'MachineCodeCard',
  props: {
    groups: { type: Array, default: () => [] },
    loading: Boolean,
    error: { type: String, default: '' }
  },
  methods: {
    async copy() {
      const ok = await copyText(this.groups.join('-'))
      if (ok) {
        toastSuccess('机器码已复制')
        this.$emit('copied')
      } else {
        toastError(null, '复制失败，请手动选中机器码复制')
      }
    }
  }
}
</script>

<style scoped>
.machine-code { display: flex; flex-direction: column; align-items: flex-start; gap: 10px; }
.machine-code__title { font-family: var(--font-serif); font-size: 18px; font-weight: 700; }
.machine-code__tip { font-size: var(--fs-small); color: var(--ink-muted); }
.machine-code__box {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 12px;
  width: 100%;
  padding: 14px 16px;
  border: 1px solid var(--line);
  border-radius: var(--radius);
  background: var(--surface);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 16px;
  letter-spacing: .06em;
  user-select: all;
}
.machine-code__box.is-empty { user-select: none; }
.machine-code__placeholder { color: var(--ink-soft); font-family: var(--font-sans); letter-spacing: 0; font-size: var(--fs-body); }
</style>
