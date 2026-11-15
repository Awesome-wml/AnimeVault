<template>
  <div v-if="total > pageSize" class="simple-pager">
    <span class="note">共 {{ total }} 条</span>
    <el-pagination background small layout="prev, pager, next" :total="total" :current-page="page"
                   :page-size="pageSize" @current-change="p => $emit('update:page', p)" />
  </div>
</template>

<script>
/** 小型分页（无每页条数选择）：用于抽屉里的事件时间线等窄空间。用 :page.sync 绑定页码；不足一页时不显示。 */
export default {
  name: 'SimplePager',
  props: {
    total: { type: Number, default: 0 },
    page: { type: Number, default: 1 },
    pageSize: { type: Number, default: 10 }
  }
}
</script>

<style scoped>
.simple-pager { display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap; }
</style>
