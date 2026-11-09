<template>
  <span class="seal" :style="{ '--seal-size': size + 'px' }" aria-hidden="true">{{ text }}</span>
</template>

<script>
/** 朱红印章（全站唯一彩色块），如产品首页“戏”。 */
export default {
  name: 'SealMark',
  props: {
    text: { type: String, default: '戏' },
    size: { type: Number, default: 30 }
  }
}
</script>

<style scoped>
.seal {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: none;
  width: var(--seal-size);
  height: var(--seal-size);
  background: var(--seal);
  color: var(--paper);
  font-family: var(--font-serif);
  font-size: calc(var(--seal-size) * .57);
  line-height: 1;
  border-radius: 2px;
}
</style>
