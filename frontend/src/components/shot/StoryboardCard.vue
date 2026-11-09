<template>
  <section class="storyboard" aria-label="四格分镜">
    <div class="storyboard__figure">
      <el-image v-if="src" class="storyboard__img" :src="src" :preview-src-list="[src]" fit="contain" alt="本段四格分镜图" />
      <MediaFrame v-else ratio="1 / 1" :tone="shot.shot_no" :label="busy ? '正在生成四格分镜…' : '还没有四格分镜'" />
    </div>
    <ol class="storyboard__legend" aria-label="四格对应的时间段">
      <li v-for="p in panels" :key="p.panel" class="storyboard__panel">
        <span class="storyboard__tag">{{ p.panel }} · {{ p.pos }}</span>
        <span class="storyboard__time">{{ range(p) }}</span>
        <span class="storyboard__text">{{ p.text }}</span>
      </li>
      <li v-if="!panels.length" class="note">这一段还没有小镜头，先拆分镜或补小镜头。</li>
    </ol>
  </section>
</template>

<script>
/**
 * 视频段的四格分镜图（左上 S1 → 右上 S2 → 左下 S3 → 右下 S4，每格对应本段一个时间段）。
 * 左边方图（点开看大图；没有时占位，生成中显示文字），右边 S1–S4 对应的时间段与小镜头文字。
 * 数据来自 /api/shots 的 storyboard_path / storyboard_panels。生成按钮在 ShotDetail 的操作行里。
 */
import { api } from '@/api'
import { timeRange } from './segment'

export default {
  name: 'StoryboardCard',
  props: {
    shot: { type: Object, required: true },
    busy: Boolean
  },
  computed: {
    src() { return this.shot.storyboard_path ? api.staticUrl(this.shot.storyboard_path) : '' },
    panels() { return this.shot.storyboard_panels || [] }
  },
  methods: { range: timeRange }
}
</script>

<style scoped>
.storyboard { display: grid; grid-template-columns: minmax(200px, 320px) minmax(0, 1fr); gap: 16px; align-items: start; }
.storyboard__figure { min-width: 0; }
.storyboard__img { display: block; width: 100%; aspect-ratio: 1 / 1; border-radius: var(--radius); overflow: hidden; background: var(--ink); }
.storyboard__legend { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 8px; font-size: var(--fs-small); }
.storyboard__panel { display: grid; grid-template-columns: 84px 84px minmax(0, 1fr); gap: 8px; align-items: baseline; }
.storyboard__tag { font-weight: 600; white-space: nowrap; }
.storyboard__time { color: var(--ink-muted); white-space: nowrap; }
.storyboard__text { line-height: 1.6; word-break: break-all; }
@media (max-width: 760px) {
  .storyboard { grid-template-columns: 1fr; }
  .storyboard__panel { grid-template-columns: 84px minmax(0, 1fr); }
  .storyboard__time { grid-column: 2; }
}
</style>
