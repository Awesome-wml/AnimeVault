<template>
  <ol class="seg-lines" :class="{ 'seg-lines--compact': compact }">
    <li v-for="(ln, i) in shown" :key="i" class="seg-lines__item">
      <span class="seg-lines__tag" :class="'seg-lines__tag--' + ln.kind">{{ speaker(ln) }}</span>
      <span class="seg-lines__text">{{ ln.text }}</span>
      <span v-if="!compact" class="seg-lines__time">{{ range(ln) }}</span>
    </li>
    <li v-if="compact && lines.length > max" class="seg-lines__more">还有 {{ lines.length - max }} 句</li>
  </ol>
</template>

<script>
/** 视频段的逐句台词：说话人 + 类型标签 + 台词（+ 段内起止秒）。compact 用于列表行，只显示前几句。 */
import { lineSpeaker, timeRange } from './segment'

export default {
  name: 'SegmentLines',
  props: {
    lines: { type: Array, default: () => [] },
    compact: Boolean,
    max: { type: Number, default: 3 }
  },
  computed: {
    shown() { return this.compact ? this.lines.slice(0, this.max) : this.lines }
  },
  methods: { speaker: lineSpeaker, range: timeRange }
}
</script>

<style scoped>
.seg-lines { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 4px; min-width: 0; }
.seg-lines__item { display: flex; align-items: baseline; gap: 8px; min-width: 0; line-height: 1.6; }
.seg-lines--compact .seg-lines__item { gap: 6px; }
.seg-lines__tag {
  flex: none;
  padding: 0 6px;
  border-radius: 4px;
  background: var(--side);
  color: var(--ink-muted);
  font-size: var(--fs-caption);
  white-space: nowrap;
}
.seg-lines__tag--onscreen { background: var(--active); color: var(--ink); }
.seg-lines__text { min-width: 0; }
.seg-lines--compact .seg-lines__text { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.seg-lines__time { flex: none; margin-left: auto; color: var(--ink-muted); font-size: var(--fs-caption); white-space: nowrap; }
.seg-lines__more { color: var(--ink-muted); font-size: var(--fs-caption); }
</style>
