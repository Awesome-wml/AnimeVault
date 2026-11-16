<template>
  <div class="warn-bar" role="alert">
    <i class="el-icon-warning warn-bar__icon"></i>
    <div class="warn-bar__body"><slot></slot></div>
  </div>
</template>

<script>
/** 醒目的黄色提示条（不阻止操作） */
export default { name: 'WarnBar' }
</script>

<style scoped>
.warn-bar {
  display: flex; gap: 10px; align-items: flex-start; padding: 10px 14px;
  background: var(--warn-bg); border: 1px solid var(--warn-line); border-radius: var(--radius);
  color: var(--warn); font-size: var(--fs-small); line-height: 1.6;
}
.warn-bar__icon { margin-top: 3px; font-size: 16px; }
.warn-bar__body { flex: 1; min-width: 0; word-break: break-all; }
</style>
