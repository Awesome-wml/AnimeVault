<template>
  <div class="center-layout">
    <main class="center-layout__card">
      <router-link to="/" class="center-layout__brand serif">DongAI</router-link>
      <slot></slot>
    </main>
  </div>
</template>

<script>
/** 居中单卡布局（无侧栏）：激活页等「进入工作台之前」的页面用。内容全部走默认插槽。 */
export default { name: 'CenterLayout' }
</script>

<style scoped>
.center-layout {
  min-height: 100vh;
  display: flex;
  justify-content: center;
  padding: 48px 20px;
  background: var(--paper);
}
.center-layout__card { width: 100%; max-width: 560px; display: flex; flex-direction: column; gap: 24px; }
.center-layout__brand { align-self: flex-start; font-size: 20px; font-weight: 700; }
</style>
