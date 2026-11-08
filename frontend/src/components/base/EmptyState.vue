<template>
  <div class="empty-state" :class="{ 'empty-state--compact': compact }">
    <Seal v-if="seal" :text="seal" class="empty-state__seal" />
    <h2 class="empty-state__title">{{ title }}</h2>
    <p v-if="description || $slots.default" class="empty-state__desc">
      <slot>{{ description }}</slot>
    </p>
    <div v-if="$slots.actions" class="empty-state__actions">
      <slot name="actions"></slot>
    </div>
  </div>
</template>

<script>
/** 空状态 / 占位：宋体标题 + 灰色说明 + 操作。compact 用于区块内。 */
import Seal from './Seal.vue'

export default {
  name: 'EmptyState',
  components: { Seal },
  props: {
    title: { type: String, required: true },
    description: { type: String, default: '' },
    seal: { type: String, default: '' },
    compact: Boolean
  }
}
</script>

<style scoped>
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 8px;
  padding: 48px 0;
  max-width: 520px;
}
.empty-state--compact { padding: 12px 0; }
.empty-state__seal { margin-bottom: 8px; }
.empty-state__title { font-family: var(--font-serif); font-size: 20px; font-weight: 700; }
.empty-state--compact .empty-state__title { font-family: var(--font-sans); font-size: var(--fs-body); font-weight: 400; color: var(--ink-muted); }
.empty-state__desc { color: var(--ink-muted); }
.empty-state__actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 8px; }
</style>
