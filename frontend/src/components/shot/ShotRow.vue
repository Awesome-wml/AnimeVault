<template>
  <button type="button" class="shot-row" :aria-current="active ? 'true' : undefined" @click="$emit('select', shot.id)">
    <span class="shot-row__no">{{ shot.shot_no }}</span>
    <MediaFrame class="shot-row__thumb" :src="thumb" :tone="shot.shot_no" :ratio="square ? '1 / 1' : '16 / 9'" />
    <span v-if="segment" class="shot-row__body">
      <span class="shot-row__meta">
        {{ sec(shot.duration) }} 秒 · {{ shot.lines.length }} 句 ·
        <StatusText :status="fill.key" :n="fill.n" />
      </span>
      <SegmentLines :lines="shot.lines" compact />
    </span>
    <span v-else class="shot-row__text">{{ shot.text || '（没有台词）' }}</span>
    <StatusText class="shot-row__status" :status="st.status" :n="st.n" />
  </button>
</template>

<script>
/**
 * 分镜列表的一行：段号 + 画面缩略图（视频段是四格分镜方图，旧数据是首帧）+ 内容 + 状态。
 * 视频段显示时长、句数、填充率和前几句台词（带说话人与类型）；旧数据（没有 lines）照旧显示两行台词。
 */
import { api } from '@/api'
import { fillStatus } from '@/components/base/status'
import { shotStatus } from './status'
import { isSegment, isSquarePicture, pictureOf, sec } from './segment'
import SegmentLines from './SegmentLines.vue'

export default {
  name: 'ShotRow',
  components: { SegmentLines },
  props: {
    shot: { type: Object, required: true },
    progress: { type: Object, default: null },
    active: Boolean
  },
  computed: {
    thumb() { return pictureOf(this.shot) ? api.staticUrl(pictureOf(this.shot)) : '' },
    square() { return isSquarePicture(this.shot) },
    st() { return shotStatus(this.shot, this.progress) },
    segment() { return isSegment(this.shot) },
    fill() { return fillStatus(this.shot.fill_rate) }
  },
  methods: { sec }
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
.shot-row__body { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
.shot-row__meta { color: var(--ink-muted); font-size: var(--fs-caption); }
.shot-row__status { font-size: var(--fs-caption); }
@media (max-width: 760px) {
  .shot-row { grid-template-columns: 28px 64px minmax(0, 1fr); gap: 10px; }
  .shot-row__status { grid-column: 3; }
}
</style>
