<template>
  <header class="page-header">
    <div class="page-header__text">
      <h1 class="page-header__title">
        <slot name="title">{{ title }}</slot>
      </h1>
      <p v-if="subtitle || $slots.subtitle" class="page-header__subtitle">
        <slot name="subtitle">{{ subtitle }}</slot>
      </p>
    </div>
    <div v-if="$slots.actions" class="page-header__actions">
      <slot name="actions"></slot>
    </div>
  </header>
</template>

<script>
/** 页面标题行：宋体大标题 + 副标题 + 右侧操作区（每页只放一个 primary 按钮） */
export default {
  name: 'PageHeader',
  props: {
    title: { type: String, default: '' },
    subtitle: { type: String, default: '' }
  }
}
</script>

<style scoped>
.page-header {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  gap: 12px;
}
.page-header__text { flex: 1 1 240px; min-width: 0; }
.page-header__title {
  font-family: var(--font-serif);
  font-size: var(--fs-title);
  font-weight: 700;
  line-height: 1.3;
}
.page-header__subtitle {
  margin-top: 2px;
  font-size: var(--fs-body);
  color: var(--ink-muted);
}
.page-header__actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}
</style>
