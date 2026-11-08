<template>
  <div class="media-frame" :style="frameStyle" data-testid="media-frame">
    <video v-if="src && isVideo" ref="video" class="media-frame__media" :class="fitClass" :src="src" :poster="poster" preload="metadata" :muted="!controls" playsinline :controls="controls" v-on="$listeners"></video>
    <img v-else-if="src" class="media-frame__media" :class="fitClass" :src="src" :alt="alt" loading="lazy" />
    <span v-else-if="glyph" class="media-frame__glyph" aria-hidden="true">{{ glyph }}</span>
    <span v-else class="media-frame__label">
      <slot>{{ label }}</slot>
    </span>
  </div>
</template>

<script>
/**
 * 图片/视频框：固定比例；有 src 显示图或视频，没有就用占位色 + 文字。
 * tone 取 1–6（对应 --tone-n），也可传任意字符串（如作品 id），会稳定地映射到一个占位色。
 * glyph：无图时显示的一个大字（如角色名首字）；fit=contain 时完整显示（三视图这类宽图）。
 * 视频的 play/ended 等事件透传给父组件（v-on="$listeners"）。
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
    glyph: { type: String, default: '' },
    fit: { type: String, default: 'cover', validator: v => ['cover', 'contain'].includes(v) },
    controls: Boolean
  },
  computed: {
    fitClass() { return 'media-frame__media--' + this.fit },
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
.media-frame__media--contain { object-fit: contain; background: transparent; }
video.media-frame__media--contain { background: var(--ink); }
.media-frame__glyph {
  font-family: var(--font-serif);
  font-size: clamp(32px, 4vw, 52px);
  line-height: 1;
  color: var(--ink-muted);
}
.media-frame__label {
  padding: 0 12px;
  color: var(--ink-muted);
  font-size: var(--fs-caption);
  text-align: center;
}
</style>
