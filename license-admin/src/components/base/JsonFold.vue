<template>
  <details class="json-fold">
    <summary>{{ label }}</summary>
    <pre class="json-fold__pre">{{ text }}</pre>
  </details>
</template>

<script>
/** 折叠展示 JSON（审计 before/after） */
export default {
  name: 'JsonFold',
  props: { value: { type: null, default: null }, label: { type: String, default: '查看' } },
  computed: { text() { return JSON.stringify(this.value, null, 2) } }
}
</script>

<style scoped>
.json-fold summary { cursor: pointer; color: var(--ink-muted); font-size: var(--fs-small); user-select: none; }
.json-fold summary:hover { color: var(--ink); }
.json-fold__pre {
  margin: 6px 0 0; padding: 8px 10px; max-height: 260px; overflow: auto; background: var(--side);
  border-radius: 6px; font-family: var(--font-mono); font-size: 12px; line-height: 1.5; white-space: pre-wrap; word-break: break-all;
}
</style>
