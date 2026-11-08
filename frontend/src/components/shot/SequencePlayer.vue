<template>
  <div class="sequence-player">
    <MediaFrame :key="index" :src="current ? current.src : ''" ratio="16 / 9" :tone="3" controls :label="emptyText" @ended="next" @play="playing = true" @pause="playing = false" />
    <div v-if="items.length" class="sequence-player__bar">
      <span class="note">镜头 {{ current.label }} · 第 {{ index + 1 }} / {{ items.length }} 段</span>
      <div class="inline-actions">
        <BaseButton variant="text" :disabled="index === 0" @click="go(index - 1)">上一段</BaseButton>
        <BaseButton variant="text" :disabled="index >= items.length - 1" @click="go(index + 1)">下一段</BaseButton>
      </div>
    </div>
  </div>
</template>

<script>
/**
 * 按顺序连续播放一组视频（成片预览）：一段播完自动切下一段。
 * items: [{ src, label }]
 */
export default {
  name: 'SequencePlayer',
  props: {
    items: { type: Array, default: () => [] },
    emptyText: { type: String, default: '还没有可预览的视频' }
  },
  data() {
    return { index: 0, playing: false }
  },
  computed: {
    current() { return this.items[this.index] || null }
  },
  watch: {
    items() { if (this.index >= this.items.length) this.index = 0 }
  },
  methods: {
    go(i) {
      const keepPlaying = this.playing
      this.index = i
      if (keepPlaying) this.autoplay()
    },
    next() {
      if (this.index < this.items.length - 1) {
        this.index++
        this.autoplay()
      }
    },
    autoplay() {
      this.$nextTick(() => {
        const v = this.$el.querySelector('video')
        // 浏览器拦截自动播放时停在新一段开头，用户手动点播放即可
        if (v) v.play().catch(e => console.info('自动播放被浏览器拦截', e.name))
      })
    }
  }
}
</script>

<style scoped>
.sequence-player { display: flex; flex-direction: column; gap: 8px; max-width: 760px; }
.sequence-player__bar { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
</style>
