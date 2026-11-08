<template>
  <div ref="host" class="ink-stage" :class="'ink-stage--' + variant" aria-hidden="true">
    <canvas v-if="mode !== 'static'" ref="canvas" class="ink-stage__canvas"></canvas>
  </div>
</template>

<script>
/**
 * 水墨背景。放进一个 position:relative + overflow:hidden 的容器里即可铺满。
 * - 有 WebGL：墨迹约 9 秒洇开后静止，只剩薄雾慢流；
 * - 无 WebGL：直接显示宣纸山水静态画；
 * - prefers-reduced-motion：只画终帧，不播放；
 * - 组件销毁或标签页隐藏时停止渲染，销毁时释放 WebGL 资源。
 */
import { painting } from './painting'

function hasWebGL() {
  try {
    const c = document.createElement('canvas')
    return !!(window.WebGLRenderingContext && (c.getContext('webgl2') || c.getContext('webgl')))
  } catch (e) {
    return false
  }
}

function prefersReducedMotion() {
  return !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches)
}

export default {
  name: 'InkStage',
  props: {
    /** hero：产品首页整屏；side：登录/注册左栏（更淡、右侧渐隐） */
    variant: { type: String, default: 'hero', validator: v => ['hero', 'side'].includes(v) },
    /** 画面横向锚点，默认按 variant 取（hero 1，side .62） */
    anchorX: { type: Number, default: null }
  },
  data() {
    return { mode: 'pending' } // pending | webgl | static
  },
  computed: {
    anchor() {
      if (this.anchorX !== null) return this.anchorX
      return this.variant === 'side' ? 0.62 : 1
    }
  },
  mounted() {
    this.stage = null
    this.reduce = prefersReducedMotion()
    this.onResize = () => { if (this.stage) this.stage.redraw() }
    this.onVisibility = () => {
      if (!this.stage) return
      if (document.hidden) this.stage.stop()
      else this.stage.start(this.reduce)
    }
    window.addEventListener('resize', this.onResize)
    document.addEventListener('visibilitychange', this.onVisibility)

    if (!hasWebGL()) {
      this.showStatic()
      return
    }
    import(/* webpackChunkName: "ink-stage" */ './stage').then(({ createInkStage }) => {
      if (this._isDestroyed) return
      const stage = createInkStage(this.$refs.canvas, this.anchor)
      if (!stage) {
        this.showStatic()
        return
      }
      this.stage = stage
      this.mode = 'webgl'
      if (!document.hidden) stage.start(this.reduce)
    }).catch(() => {
      if (!this._isDestroyed) this.showStatic()
    })
  },
  beforeDestroy() {
    window.removeEventListener('resize', this.onResize)
    document.removeEventListener('visibilitychange', this.onVisibility)
    if (this.stage) {
      this.stage.dispose()
      this.stage = null
    }
  },
  methods: {
    showStatic() {
      this.mode = 'static'
      this.$nextTick(() => {
        const img = painting()
        img.className = 'ink-stage__canvas ink-stage__canvas--static'
        this.$refs.host.appendChild(img)
      })
    }
  }
}
</script>

<style scoped>
.ink-stage {
  position: absolute;
  inset: 0;
  z-index: 0;
  pointer-events: none;
}
.ink-stage__canvas,
.ink-stage >>> .ink-stage__canvas--static {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  object-fit: cover;
  object-position: right bottom;
  display: block;
}
.ink-stage--side {
  opacity: .62;
  -webkit-mask-image: linear-gradient(90deg, #000 62%, transparent 100%);
  mask-image: linear-gradient(90deg, #000 62%, transparent 100%);
}
.ink-stage--side .ink-stage__canvas,
.ink-stage--side >>> .ink-stage__canvas--static {
  object-position: 62% bottom;
}
@media (max-width: 760px) {
  .ink-stage--hero { opacity: .75; }
  .ink-stage--side { -webkit-mask-image: none; mask-image: none; }
}
</style>
