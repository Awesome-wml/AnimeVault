<template>
  <div class="shot-assets">
    <span v-if="prevFrame" class="shot-assets__chip" :class="{ 'is-empty': !prevFrame.image }"
          title="首帧参考（上一段尾帧）">
      <el-image v-if="prevFrame.image" class="shot-assets__thumb" :src="url(prevFrame.image)"
                :preview-src-list="[url(prevFrame.image)]" fit="cover" alt="首帧参考" />
      <span v-else class="shot-assets__thumb shot-assets__thumb--empty">首</span>
      <span class="shot-assets__name">首帧参考</span>
      <span v-if="!prevFrame.image" class="shot-assets__todo">{{ prevFrame.reason || '无' }}</span>
    </span>
    <span v-for="(a, i) in list" :key="i" class="shot-assets__chip" :class="{ 'is-empty': !a.img }"
          :title="`${a.label && a.label !== a.type ? a.label : a.type}：${a.name}${a.form ? '（' + a.form + '）' : ''}`">
      <el-image v-if="a.img" class="shot-assets__thumb" :src="url(a.img)" :preview-src-list="[url(a.img)]" fit="cover" :alt="a.name" />
      <span v-else class="shot-assets__thumb shot-assets__thumb--empty" aria-hidden="true">{{ a.name.slice(0, 1) }}</span>
      <span class="shot-assets__name">{{ a.name }}</span>
      <span v-if="!a.img" class="shot-assets__todo">未出图</span>
    </span>
    <span v-if="!list.length" class="note">还没有匹配到角色、场景或道具。</span>
  </div>
</template>

<script>
/**
 * 镜头用到的资产（后端按场次与台词/提示词匹配，角色 → 场景 → 道具）。
 * 已出图的点缩略图看大图；还没出图的显示占位与「未出图」，到资产页生成参考图后自动带上。
 */
import { api } from '@/api'

export default {
  name: 'ShotAssets',
  props: {
    assets: { type: Array, default: () => [] },
    prevFrame: { type: Object, default: null }
  },
  computed: {
    // “画面”是本镜参考图，已在上方大图显示
    list() { return this.assets.filter(a => a.type !== '分镜参考') }
  },
  methods: {
    url: api.staticUrl
  }
}
</script>

<style scoped>
.shot-assets { display: flex; flex-wrap: wrap; gap: 6px; }
.shot-assets__chip {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-height: 36px;
  padding: 0 12px 0 4px;
  border: 1px solid var(--line);
  border-radius: var(--radius);
  background: var(--surface);
  font-size: var(--fs-small);
  color: var(--ink);
}
.shot-assets__chip.is-empty { background: var(--side); }
.shot-assets__thumb { width: 28px; height: 28px; border-radius: 4px; flex: none; }
.shot-assets__thumb--empty {
  display: flex; align-items: center; justify-content: center;
  background: var(--line); color: var(--ink-muted);
  font-family: var(--font-serif); font-size: 14px;
}
.shot-assets__name { min-width: 0; }
.shot-assets__todo { color: var(--ink-muted); font-size: var(--fs-caption); }
</style>
