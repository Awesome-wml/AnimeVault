<template>
  <article class="asset-card" :class="{ 'asset-card--lg': size === 'lg' }">
    <component :is="to ? 'router-link' : 'div'" :to="to" class="asset-card__main" @click="$emit('open')">
      <MediaFrame :src="src" :ratio="ratio" :tone="tone" :label="placeholder" :alt="title" />
      <div class="asset-card__text">
        <div class="asset-card__title">{{ title }}</div>
        <div v-if="meta || $slots.meta" class="asset-card__meta">
          <slot name="meta">{{ meta }}</slot>
        </div>
      </div>
    </component>
    <div v-if="$slots.actions" class="asset-card__actions">
      <slot name="actions"></slot>
    </div>
  </article>
</template>

<script>
/**
 * 图 + 宋体名称 + 灰色说明的卡片。作品、角色、场景、道具共用。
 * 整卡可点（to 或 @open），右下角 #actions 放次要操作（如删除）。
 */
import MediaFrame from './MediaFrame.vue'

export default {
  name: 'AssetCard',
  components: { MediaFrame },
  props: {
    title: { type: String, required: true },
    meta: { type: String, default: '' },
    src: { type: String, default: '' },
    ratio: { type: String, default: '16 / 9' },
    tone: { type: [Number, String], default: 2 },
    placeholder: { type: String, default: '' },
    to: { type: [String, Object], default: null },
    /** md：首页最近作品（16px 标题）；lg：全部作品（18px 标题） */
    size: { type: String, default: 'md' }
  }
}
</script>

<style scoped>
.asset-card { position: relative; display: flex; flex-direction: column; gap: 8px; min-width: 0; }
.asset-card__main { display: flex; flex-direction: column; gap: 8px; color: var(--ink); cursor: pointer; }
.asset-card--lg .asset-card__main { gap: 10px; }
.asset-card__main:hover .asset-card__title { text-decoration: underline; text-underline-offset: 4px; }
.asset-card__title {
  font-family: var(--font-serif);
  font-size: 16px;
  font-weight: 700;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.asset-card--lg .asset-card__title { font-size: 18px; }
.asset-card__meta { font-size: var(--fs-small); color: var(--ink-muted); }
.asset-card__actions {
  position: absolute;
  right: 0;
  bottom: 0;
  display: flex;
  gap: 4px;
}
</style>
