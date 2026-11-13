<template>
  <article class="asset-card" :class="{ 'asset-card--lg': size === 'lg', 'is-selected': selected, 'is-clickable': clickable }">
    <component
      :is="to ? 'router-link' : 'div'"
      :to="to"
      class="asset-card__main"
      :role="!to && clickable ? 'button' : undefined"
      :tabindex="!to && clickable ? 0 : undefined"
      :aria-pressed="selectable ? String(selected) : undefined"
      @click="$emit('open')"
      @keydown.enter="!to && $emit('open')"
    >
      <MediaFrame :src="src" :ratio="ratio" :tone="tone" :label="placeholder" :glyph="glyph" :fit="fit" :alt="title" :preview="preview" />
      <div class="asset-card__text">
        <div class="asset-card__head">
          <div class="asset-card__title" :title="title">{{ title }}</div>
          <span v-if="badge || $slots.badge" class="asset-card__badge"><slot name="badge">{{ badge }}</slot></span>
        </div>
        <div v-if="meta || $slots.meta" class="asset-card__meta" :class="{ 'is-clamped': clamp }" :title="clamp ? meta : undefined">
          <slot name="meta">{{ meta }}</slot>
        </div>
      </div>
    </component>
    <div v-if="$slots.default" class="asset-card__body"><slot></slot></div>
    <div v-if="$slots.footer" class="asset-card__footer"><slot name="footer"></slot></div>
    <div v-if="$slots.actions" class="asset-card__actions">
      <slot name="actions"></slot>
    </div>
  </article>
</template>

<script>
/**
 * 图 + 名称 + 灰色说明的卡片。作品、角色、场景、道具、风格选项共用。
 * - 整卡可点（to 或 @open）
 * - badge：名称右侧的小字（主角 / 室外 / 信物）
 * - clamp：说明只显示一行，悬停看全文
 * - 默认插槽：卡片下方的附加控件（如角色音色）
 * - #footer：底部操作行（主操作 + 更多）
 * - #actions：右下角浮动的次要操作（作品卡的删除）
 * - selected / selectable：单选卡片（风格页）
 */
import MediaFrame from './MediaFrame.vue'

export default {
  name: 'AssetCard',
  components: { MediaFrame },
  props: {
    title: { type: String, required: true },
    meta: { type: String, default: '' },
    badge: { type: String, default: '' },
    src: { type: String, default: '' },
    ratio: { type: String, default: '16 / 9' },
    tone: { type: [Number, String], default: 2 },
    placeholder: { type: String, default: '' },
    glyph: { type: String, default: '' },
    fit: { type: String, default: 'cover' },
    to: { type: [String, Object], default: null },
    clamp: Boolean,
    selected: Boolean,
    selectable: Boolean,
    /** 点击图片放大查看大图（资产卡片开启） */
    preview: Boolean,
    /** md：首页最近作品、资产（16px 标题）；lg：全部作品（18px 标题） */
    size: { type: String, default: 'md' }
  },
  computed: {
    clickable() { return !!this.to || !!this.$listeners.open }
  }
}
</script>

<style scoped>
.asset-card { position: relative; display: flex; flex-direction: column; gap: 8px; min-width: 0; }
.asset-card__main { display: flex; flex-direction: column; gap: 8px; color: var(--ink); }
.asset-card.is-clickable .asset-card__main { cursor: pointer; }
.asset-card--lg .asset-card__main { gap: 10px; }
.asset-card.is-clickable .asset-card__main:hover .asset-card__title { text-decoration: underline; text-underline-offset: 4px; }
.asset-card.is-selected .media-frame { outline: 2px solid var(--ink); outline-offset: 2px; }
.asset-card__head { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; min-width: 0; }
.asset-card__title {
  min-width: 0;
  font-family: var(--font-serif);
  font-size: 16px;
  font-weight: 700;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.asset-card--lg .asset-card__title { font-size: 18px; }
.asset-card__badge { flex: none; font-size: var(--fs-caption); color: var(--ink-muted); }
.asset-card__meta { font-size: var(--fs-small); color: var(--ink-muted); }
.asset-card__meta.is-clamped { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.asset-card__body { display: flex; flex-direction: column; gap: 4px; }
.asset-card__footer { display: flex; align-items: center; justify-content: space-between; gap: 8px; min-height: 36px; }
.asset-card__actions {
  position: absolute;
  right: 0;
  bottom: 0;
  display: flex;
  gap: 4px;
}
</style>
