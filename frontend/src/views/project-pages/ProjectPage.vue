<template>
  <div class="page">
    <PageHeader :title="title" :subtitle="subtitle">
      <template v-if="$slots.actions" #actions><slot name="actions"></slot></template>
    </PageHeader>
    <slot></slot>
  </div>
</template>

<script>
/** 作品内页面的统一外框：标题行 + 内容。二期各页重做时继续沿用。 */
export default {
  name: 'ProjectPage',
  props: {
    title: { type: String, required: true },
    subtitle: { type: String, default: '' }
  }
}
</script>
