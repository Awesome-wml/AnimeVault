<template>
  <section class="storyboard" :class="src ? '' : 'storyboard--empty'" aria-label="四格分镜">
    <div class="storyboard__figure">
      <el-image v-if="src" class="storyboard__img" :src="src" :preview-src-list="[src]" fit="contain" alt="本段四格分镜图" />
      <div v-else class="storyboard__empty">{{ busy ? '正在生成四格分镜…' : '还没有四格分镜，点上方「生成画面」出图' }}</div>
    </div>
    <ol v-if="src" class="storyboard__legend" aria-label="四格对应的时间段">
      <li v-for="p in panels" :key="p.panel" class="storyboard__panel">
        <span class="storyboard__tag">{{ p.panel }} · {{ p.pos }}</span>
        <span class="storyboard__time">{{ range(p) }}</span>
        <span class="storyboard__text">{{ p.text }}</span>
      </li>
      <li v-if="!panels.length" class="note">这一段还没有小镜头，先拆分镜或补小镜头。</li>
    </ol>
    <p v-else-if="panels.length" class="storyboard__hint note">
      本段 {{ panels.length }} 个小镜头，镜头细节见下方「段内小镜头」；四格文案在「提示词与生成参数」里查看。
    </p>
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
.storyboard { display: grid; grid-template-columns: minmax(160px, 260px) minmax(0, 1fr); gap: 16px; align-items: start; }
.storyboard--empty { grid-template-columns: minmax(0, 1fr); gap: 8px; }
.storyboard__figure { min-width: 0; }
.storyboard__empty {
  height: 120px; display: flex; align-items: center; justify-content: center;
  padding: 0 12px; text-align: center; color: var(--ink-muted);
  font-size: var(--fs-caption); border: 1px dashed var(--line);
  border-radius: var(--radius); background: var(--side);
}
.storyboard__img { display: block; width: 100%; aspect-ratio: 1 / 1; border-radius: var(--radius); overflow: hidden; background: var(--ink); }
.storyboard__legend { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 8px; font-size: var(--fs-small); min-width: 0; }
.storyboard__hint { margin: 0; min-width: 0; }
.storyboard__panel { display: grid; grid-template-columns: auto auto; column-gap: 12px; row-gap: 4px; align-items: baseline; }
.storyboard__tag { font-weight: 600; white-space: nowrap; }
.storyboard__time { color: var(--ink-muted); white-space: nowrap; }
.storyboard__text { line-height: 1.6; word-break: break-all; grid-column: 1 / -1; min-width: 0; }
@media (max-width: 760px) {
  .storyboard, .storyboard--empty { grid-template-columns: 1fr; }
}
</style>
