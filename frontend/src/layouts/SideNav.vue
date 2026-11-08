<template>
  <aside class="side-nav">
    <nav :aria-label="label" class="side-nav__main">
      <slot name="head">
        <router-link v-if="brand" to="/home" class="side-nav__brand">{{ brand }}</router-link>
      </slot>
      <div v-for="group in groups" :key="group.key || group.title" class="side-nav__group">
        <div v-if="group.title" class="side-nav__title">{{ group.title }}</div>
        <slot v-if="group.slot" :name="group.slot"></slot>
        <router-link
          v-for="item in group.items"
          :key="item.label"
          :to="item.to"
          class="side-nav__item"
          :class="{ 'is-active': isActive(item) }"
          :aria-current="isActive(item) ? 'page' : null"
        >
          <span class="side-nav__label">{{ item.label }}</span>
          <span v-if="item.alert" class="side-nav__count side-nav__count--alert">{{ item.alert }}</span>
          <span v-else-if="item.count !== undefined && item.count !== null" class="side-nav__count">{{ item.count }}</span>
        </router-link>
      </div>
    </nav>
    <div v-if="$slots.footer" class="side-nav__footer">
      <slot name="footer"></slot>
    </div>
  </aside>
</template>

<script>
/**
 * 数据驱动的侧栏。
 * groups: [{ key, title, slot?, items: [{ label, to, count?, alert?, match? }] }]
 *  - count：灰色数字；alert：印章色提示（如“2 条失败”），二者有 alert 时只显示 alert
 *  - match：判断当前项的正则（默认按路径前缀匹配 to）
 *  - slot：在该组标题下插入具名插槽（作品侧栏的剧集选择器）
 */
export default {
  name: 'SideNav',
  props: {
    groups: { type: Array, required: true },
    brand: { type: String, default: '' },
    label: { type: String, default: '主菜单' }
  },
  methods: {
    isActive(item) {
      const path = this.$route.path
      if (item.match) return item.match.test(path)
      const target = this.$router.resolve(item.to).route.path
      return path === target || path.startsWith(target + '/')
    }
  }
}
</script>

<style scoped>
.side-nav {
  flex: 0 0 var(--side-w);
  min-width: 0;
  background: var(--side);
  padding: 16px 10px;
  display: flex;
  flex-direction: column;
  gap: 18px;
}
.side-nav__main { display: flex; flex-direction: column; gap: 18px; flex: 1; }
.side-nav__brand,
.side-nav >>> .side-nav__name {
  padding: 0 10px 4px;
  font-family: var(--font-serif);
  font-size: 20px;
  font-weight: 700;
  color: var(--ink);
}
.side-nav >>> .side-nav__name { line-height: 1.3; }
.side-nav__group { display: flex; flex-direction: column; gap: 2px; }
.side-nav__title { padding: 0 10px; font-size: var(--fs-caption); color: var(--ink-muted); }
.side-nav__item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  min-height: 36px;
  padding: 0 10px;
  border-radius: var(--radius-nav);
  color: var(--ink);
  font-size: var(--fs-body);
}
.side-nav__item:hover { background: var(--hover); }
.side-nav__item.is-active { background: var(--active); font-weight: 600; }
.side-nav__count { font-size: var(--fs-caption); color: var(--ink-muted); font-weight: 400; }
.side-nav__count--alert { color: var(--seal); }
.side-nav__footer { display: flex; flex-direction: column; gap: 2px; }

/* 窄屏：侧栏变成顶部一条，菜单横排换行 */
@media (max-width: 760px) {
  .side-nav { flex: 1 1 100%; padding: 12px; gap: 10px; }
  .side-nav__main { gap: 10px; }
  .side-nav__group { flex-direction: row; flex-wrap: wrap; align-items: center; gap: 2px 4px; }
  .side-nav__title { flex: 0 0 100%; }
  .side-nav__item { min-height: 32px; }
  .side-nav__footer { flex-direction: row; flex-wrap: wrap; align-items: center; }
}
</style>
