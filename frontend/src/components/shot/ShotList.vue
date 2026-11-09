<template>
  <section class="shot-list" aria-label="镜头列表">
    <ShotRow
      v-for="s in shots"
      :key="s.id"
      :shot="s"
      :progress="progress[s.shot_no] || null"
      :active="s.id === value"
      @select="id => $emit('input', id)"
    />
  </section>
</template>

<script>
/** 镜头列表。v-model 为当前选中的分镜 id；progress 为 { 镜号: SSE 进度 }。 */
import ShotRow from './ShotRow.vue'

export default {
  name: 'ShotList',
  components: { ShotRow },
  props: {
    shots: { type: Array, default: () => [] },
    value: { type: String, default: '' },
    progress: { type: Object, default: () => ({}) }
  }
}
</script>

<style scoped>
.shot-list { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
</style>
