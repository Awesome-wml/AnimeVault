<template>
  <button type="button" class="shot-row" :aria-current="active ? 'true' : undefined" @click="$emit('select', shot.id)">
    <span class="shot-row__no">{{ shot.shot_no }}</span>
    <MediaFrame class="shot-row__thumb" :src="thumb" :tone="shot.shot_no" ratio="16 / 9" />
    <span class="shot-row__text">{{ shot.text || '（没有台词）' }}</span>
    <StatusText class="shot-row__status" :status="st.status" :n="st.n" />
  </button>
</template>

<script>
/** 分镜列表的一行：镜号 + 画面缩略图 + 台词（两行）+ 状态。 */
import { api } from '@/api'
import { shotStatus } from './status'

export default {
  name: 'ShotRow',
  props: {
    shot: { type: Object, required: true },
    progress: { type: Object, default: null },
    active: Boolean
  },
  computed: {
    thumb() { return this.shot.img_path ? api.staticUrl(this.shot.img_path) : '' },
    st() { return shotStatus(this.shot, this.progress) }
  }
}
</script>

<style scoped>
.shot-row {
  display: grid;
  grid-template-columns: 40px 84px minmax(0, 1fr) auto;
  align-items: center;
  gap: 16px;
  width: 100%;
  min-height: 64px;
  padding: 8px 10px;
  border: 0;
  border-radius: var(--radius);
  background: transparent;
  color: var(--ink);
  text-align: left;
  font-size: var(--fs-small);
}
.shot-row:hover { background: var(--hover-soft); }
.shot-row[aria-current="true"] { background: var(--active); }
.shot-row__no { font-family: var(--font-serif); font-size: 18px; text-align: center; }
.shot-row__text {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  line-height: 1.6;
}
.shot-row__status { font-size: var(--fs-caption); }
@media (max-width: 760px) {
  .shot-row { grid-template-columns: 28px 64px minmax(0, 1fr); gap: 10px; }
  .shot-row__status { grid-column: 3; }
}
</style>
