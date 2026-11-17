<template>
  <div class="update-notes">
    <p v-if="version" class="update-notes__head">
      版本 {{ version }}<span v-if="meta"> · {{ meta }}</span>
    </p>
    <pre v-if="notes" class="update-notes__body">{{ notes }}</pre>
    <p v-else class="update-notes__empty">这个版本没有填写更新说明。</p>
  </div>
</template>

<script>
/** 更新说明展示：版本号 + 发布日期/大小 + 说明正文（纯文本，保留换行）。数据由父组件传入。 */
export default {
  name: 'UpdateNotes',
  props: {
    version: { type: String, default: '' },
    notes: { type: String, default: '' },
    meta: { type: String, default: '' }
  }
}
</script>

<style scoped>
.update-notes { display: flex; flex-direction: column; gap: 8px; min-width: 0; }
.update-notes__head { font-size: var(--fs-small); color: var(--ink-muted); }
.update-notes__body {
  margin: 0;
  max-height: 260px;
  overflow: auto;
  padding: 12px 14px;
  border: 1px solid var(--line);
  border-radius: var(--radius);
  background: var(--surface);
  font-family: inherit;
  font-size: var(--fs-body);
  line-height: var(--lh-body);
  white-space: pre-wrap;
  word-break: break-word;
}
.update-notes__empty { font-size: var(--fs-body); color: var(--ink-muted); }
</style>
