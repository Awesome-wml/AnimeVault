<template>
  <div class="legacy-scope legacy-panel">
    <slot></slot>
  </div>
</template>

<script>
/**
 * 旧面板（NovelPanel / AssetPanel / CharacterPanel / ShotPanel）的过渡容器。
 * 旧面板按暗色主题写死了大量颜色，这里给它们一块暗色底，并启用限定在
 * .legacy-scope 内的旧样式（styles/legacy.css）。二期（T-197）重做后删除。
 */
export default { name: 'LegacyPanel' }
</script>

<style scoped>
.legacy-panel {
  background: var(--bg-dark-primary);
  color: var(--text-light);
  border-radius: var(--radius);
  padding: 20px;
  min-width: 0;
}
@media (max-width: 760px) {
  .legacy-panel { padding: 12px; }
}
</style>
