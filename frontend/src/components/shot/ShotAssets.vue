<template>
  <div class="shot-assets">
    <span v-for="(a, i) in list" :key="i" class="shot-assets__chip" :title="`${a.type}：${a.name}`">
      <el-image class="shot-assets__thumb" :src="url(a.img)" :preview-src-list="[url(a.img)]" fit="cover" :alt="a.name" />
      {{ a.name }}
    </span>
    <span v-if="!list.length" class="note">还没有匹配到带参考图的角色、场景或道具。</span>
  </div>
</template>

<script>
/**
 * 镜头用到的资产（后端按名称在台词/提示词里匹配，且已有参考图的才列出）。点缩略图看大图。
 * 想让某个资产出现：在资产页给它生成参考图，并在台词或提示词里写上它的名字。
 */
import { api } from '@/api'

export default {
  name: 'ShotAssets',
  props: { assets: { type: Array, default: () => [] } },
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
.shot-assets__thumb { width: 28px; height: 28px; border-radius: 4px; flex: none; }
</style>
