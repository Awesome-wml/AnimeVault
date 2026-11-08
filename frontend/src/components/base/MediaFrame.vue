<template>
  <div class="media-frame" :style="frameStyle">
    <video v-if="src && isVideo" class="media-frame__media" :src="src" :poster="poster" preload="metadata" muted playsinline :controls="controls"></video>
    <img v-else-if="src" class="media-frame__media" :src="src" :alt="alt" loading="lazy" />
    <span v-else class="media-frame__label">
      <slot>{{ label }}</slot>
    </span>
  </div>
</template>

<script>
/**
 * 图片/视频框：固定比例；有 src 显示图或视频，没有就用占位色 + 文字。
 * tone 取 1–6（对应 --tone-n），也可传任意字符串（如作品 id），会稳定地映射到一个占位色。
 */
const VIDEO_RE = /\.(mp4|webm|mov|m4v)(\?|$)/i

export default {
  name: 'MediaFrame',
  props: {
    src: { type: String, default: '' },
    poster: { type: String, default: '' },
    ratio: { type: String, default: '16 / 9' },
    tone: { type: [Number, String], default: 2 },
    label: { type: String, default: '' },
    alt: { type: String, default: '' },
    controls: Boolean
  },
  computed: {
    isVideo() { return VIDEO_RE.test(this.src) },
    toneIndex() {
      if (typeof this.tone === 'number') return ((this.tone - 1) % 6 + 6) % 6 + 1
      let h = 0
      for (const ch of String(this.tone)) h = (h * 31 + ch.charCodeAt(0)) >>> 0
      return (h % 6) + 1
    },
    frameStyle() {
      return { aspectRatio: this.ratio, background: `var(--tone-${this.toneIndex})` }
    }
  }
}
</script>

<style scoped>
.media-frame {
  position: relative;
  width: 100%;
  border-radius: var(--radius);
  overflow: hidden;
  display: flex;
  align-items: center;
  justify-content: center;
}
.media-frame__media {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  object-fit: cover;
  background: var(--ink);
}
.media-frame__label {
  padding: 0 12px;
  color: var(--ink-muted);
  font-size: var(--fs-caption);
  text-align: center;
}
</style>
