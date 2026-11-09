<template>
  <div class="card-grid card-grid--choice" role="radiogroup" :aria-label="label">
    <AssetCard
      v-for="(item, i) in items"
      :key="item.id"
      :title="item.name"
      :meta="item.description"
      :tone="i + toneOffset"
      :ratio="ratio"
      selectable
      :selected="item.id === value"
      @open="$emit('input', item.id)"
    />
  </div>
</template>

<script>
/**
 * 单选卡片网格（风格页的媒介行、题材行共用）：每张卡标题 + 一句描述，已选卡高亮。
 * v-model 为选中项的 id；items 为 [{ id, name, description }]。
 */
export default {
  name: 'StyleChoiceGrid',
  props: {
    items: { type: Array, default: () => [] },
    value: { type: String, default: '' },
    label: { type: String, required: true },
    ratio: { type: String, default: '4 / 3' },
    /** 占位色起点（两行网格错开配色） */
    toneOffset: { type: Number, default: 1 }
  }
}
</script>
