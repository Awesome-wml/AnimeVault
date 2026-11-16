<template>
  <div class="base-table">
    <el-table v-loading="loading" :data="data" :empty-text="emptyText" style="width: 100%" v-bind="$attrs" v-on="$listeners">
      <slot></slot>
    </el-table>
    <div v-if="total > 0" class="base-table__pager">
      <span class="note">共 {{ total }} 条</span>
      <el-pagination background small layout="prev, pager, next, sizes" :total="total" :current-page="page"
                     :page-size="pageSize" :page-sizes="[20, 50, 100]"
                     @current-change="p => $emit('update:page', p)"
                     @size-change="s => $emit('update:pageSize', s)" />
    </div>
  </div>
</template>

<script>
/**
 * 表格 + 分页封装。页码和每页条数用 .sync 绑定：
 *   <BaseTable :data="items" :total="total" :page.sync="page" :page-size.sync="pageSize" @page-change=...>
 * 页码或每页条数变化时触发 change，页面据此重新取数。
 */
export default {
  name: 'BaseTable',
  inheritAttrs: false,
  props: {
    data: { type: Array, default: () => [] },
    loading: { type: Boolean, default: false },
    total: { type: Number, default: 0 },
    page: { type: Number, default: 1 },
    pageSize: { type: Number, default: 20 },
    emptyText: { type: String, default: '暂无数据' }
  }
}
</script>

<style scoped>
.base-table { min-width: 0; }
.base-table__pager { display: flex; justify-content: space-between; align-items: center; padding: 14px 0 0; gap: 12px; flex-wrap: wrap; }
</style>
