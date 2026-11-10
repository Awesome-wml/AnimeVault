<template>
  <ol class="beats" aria-label="段内小镜头">
    <li v-for="(b, i) in beats" :key="i" class="beats__item">
      <span class="beats__time">{{ range(b) }}</span>
      <span class="beats__bar" :style="barStyle(b)" aria-hidden="true"></span>
      <span class="beats__desc">
        <strong>{{ [b.shot_size, b.camera, b.move].filter(Boolean).join(' · ') || '镜头' }}</strong>
        <span v-if="b.action"> — {{ b.action }}</span>
        <span v-if="b.expression" class="beats__expr">［{{ b.expression }}］</span>
        <span v-if="refs(b)" class="beats__refs">（{{ refs(b) }}）</span>
        <span v-if="b.composition" class="beats__extra">构图：{{ b.composition }}</span>
        <span v-if="b.boundary" class="beats__extra beats__fx">特效边界：{{ b.boundary }}</span>
      </span>
    </li>
  </ol>
</template>

<script>
/** 段内小镜头时间轴：起止秒 + 在整段中的位置条 + 景别/机位/运镜/构图/动作/表情/特效边界 + 本镜说出的台词序号。只读。 */
import { timeRange } from './segment'

export default {
  name: 'BeatTimeline',
  props: {
    beats: { type: Array, default: () => [] },
    duration: { type: Number, default: 15 }
  },
  methods: {
    range: timeRange,
    barStyle(b) {
      const d = this.duration || 1
      return { '--from': `${(b.start / d) * 100}%`, '--to': `${(b.end / d) * 100}%` }
    },
    refs(b) {
      return (b.line_refs || []).length ? `第 ${b.line_refs.join('、')} 句` : ''
    }
  }
}
</script>

<style scoped>
.beats { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 6px; font-size: var(--fs-small); }
.beats__item { display: grid; grid-template-columns: 92px 120px minmax(0, 1fr); gap: 10px; align-items: center; }
.beats__time { color: var(--ink-muted); white-space: nowrap; }
.beats__bar {
  height: 6px;
  border-radius: 3px;
  background: linear-gradient(to right, var(--line) var(--from), var(--ink-muted) var(--from), var(--ink-muted) var(--to), var(--line) var(--to));
}
.beats__refs { color: var(--ink-muted); }
.beats__expr { color: var(--ink-muted); font-style: italic; }
.beats__extra { display: block; color: var(--ink-muted); margin-top: 2px; }
.beats__fx { font-style: italic; }
@media (max-width: 760px) {
  .beats__item { grid-template-columns: 80px minmax(0, 1fr); }
  .beats__bar { display: none; }
}
</style>
