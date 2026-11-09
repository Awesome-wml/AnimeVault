<template>
  <component
    :is="tag"
    v-bind="linkAttrs"
    class="base-btn"
    :class="['base-btn--' + variant, { 'base-btn--block': block, 'base-btn--lg': size === 'lg', 'base-btn--strong': strong, 'is-loading': loading }]"
    :disabled="tag === 'button' ? (disabled || loading) : undefined"
    :aria-disabled="disabled || loading ? 'true' : undefined"
    @click="onClick"
  >
    <i v-if="loading" class="el-icon-loading base-btn__spin" aria-hidden="true"></i>
    <slot></slot>
  </component>
</template>

<script>
/**
 * 按钮。variant：
 *  primary   墨色实心（每页只用一次）
 *  secondary 描边
 *  text      灰色文字按钮（表格操作、次要操作，删除也用它，靠二次确认防误删）
 *            加 strong：墨色文字，用作卡片/行内的主操作（如“生成三视图”）
 * 传 to 时渲染为 router-link。
 */
export default {
  name: 'BaseButton',
  props: {
    variant: { type: String, default: 'secondary', validator: v => ['primary', 'secondary', 'text'].includes(v) },
    size: { type: String, default: 'md' },
    type: { type: String, default: 'button' },
    to: { type: [String, Object], default: null },
    block: Boolean,
    strong: Boolean,
    loading: Boolean,
    disabled: Boolean
  },
  computed: {
    tag() { return this.to ? 'router-link' : 'button' },
    linkAttrs() { return this.to ? { to: this.to } : { type: this.type } }
  },
  methods: {
    onClick(e) {
      if (this.disabled || this.loading) {
        e.preventDefault()
        return
      }
      this.$emit('click', e)
    }
  }
}
</script>

<style scoped>
.base-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  min-height: var(--control-h);
  padding: 0 18px;
  border: 1px solid transparent;
  border-radius: var(--radius);
  font-size: var(--fs-body);
  font-weight: 500;
  line-height: 1;
  white-space: nowrap;
  text-decoration: none;
  cursor: pointer;
}
.base-btn--lg { min-height: var(--control-h-lg); font-size: 15px; }
.base-btn--block { display: flex; width: 100%; }

.base-btn--primary { background: var(--ink); color: #fff; }
.base-btn--primary:hover { opacity: .86; }

.base-btn--secondary { background: var(--surface); color: var(--ink); border-color: var(--line); }
.base-btn--secondary:hover { background: var(--hover-soft); border-color: var(--ink-soft); }

.base-btn--text {
  min-height: 36px;
  padding: 0 4px;
  background: transparent;
  color: var(--ink-muted);
  font-size: var(--fs-small);
  font-weight: 400;
}
.base-btn--text:hover { color: var(--ink); }
.base-btn--text.base-btn--strong { color: var(--ink); font-weight: 500; }
.base-btn--text.base-btn--strong:hover { text-decoration: underline; text-underline-offset: 4px; }

.base-btn:disabled, .base-btn[aria-disabled="true"] { cursor: not-allowed; opacity: .55; }
.base-btn__spin { font-size: 14px; }
</style>
