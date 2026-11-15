<template>
  <div class="page">
    <PageHeader title="申请单" subtitle="用户在软件里提交的机器码和邮箱。审核后签发授权，或驳回。" />

    <el-form inline class="filters" @submit.native.prevent="search">
      <el-form-item>
        <el-select v-model="status" placeholder="全部状态" clearable style="width: 140px" data-testid="request-filter-status" @change="search">
          <el-option v-for="s in statusOptions" :key="s.value" :label="s.label" :value="s.value" />
        </el-select>
      </el-form-item>
      <el-form-item><el-button @click="load">刷新</el-button></el-form-item>
    </el-form>

    <BaseTable :data="items" :loading="loading" :total="total" :page.sync="page" :page-size.sync="pageSize"
               empty-text="没有符合条件的申请单" data-testid="request-table">
      <el-table-column label="提交时间" width="140"><template slot-scope="{ row }">{{ fmt(row.created_at) }}</template></el-table-column>
      <el-table-column label="邮箱" min-width="170" show-overflow-tooltip>
        <template slot-scope="{ row }"><span :data-testid="'req-email-' + row.id">{{ row.email }}</span></template>
      </el-table-column>
      <el-table-column label="机器码" min-width="150">
        <template slot-scope="{ row }">
          <span class="mono small" :title="row.machine_code">{{ shortCode(row.machine_code) }}</span>
          <div class="cell-sub">{{ row.components_count }} 个分量</div>
        </template>
      </el-table-column>
      <el-table-column label="备注" min-width="120" show-overflow-tooltip><template slot-scope="{ row }">{{ row.note || '-' }}</template></el-table-column>
      <el-table-column label="状态" width="100">
        <template slot-scope="{ row }"><StatusTag kind="request" :status="row.status" /></template>
      </el-table-column>
      <el-table-column label="处理" min-width="150">
        <template slot-scope="{ row }">
          <template v-if="row.status === 'pending'"><span class="muted">-</span></template>
          <template v-else>
            <div class="small">{{ handler(row) }} · {{ fmt(row.handled_at) }}</div>
            <div v-if="row.lid" class="cell-sub mono" :data-testid="'req-lid-' + row.id">{{ row.lid }}</div>
            <div v-else-if="row.reason" class="cell-sub" :title="row.reason">{{ row.reason }}</div>
          </template>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="130">
        <template slot-scope="{ row }">
          <span v-if="canHandle(row)" class="inline-actions">
            <el-button type="text" :data-testid="'req-issue-' + row.id" @click="openIssue(row)">签发</el-button>
            <el-button type="text" class="danger-text" :data-testid="'req-reject-' + row.id" @click="openReject(row)">驳回</el-button>
          </span>
          <span v-else class="muted">-</span>
        </template>
      </el-table-column>
    </BaseTable>

    <RequestIssueDialog :visible.sync="issueVisible" :request="current" @issued="onHandled" @stale="onHandled" />

    <ConfirmDialog :visible.sync="rejectVisible" title="驳回申请单" confirm-label="确认驳回" danger :loading="rejecting"
                   @confirm="doReject">
      <p>确认驳回 {{ current && current.email }} 的申请？驳回后不能再签发，用户可以重新提交。</p>
      <el-input v-model="reason" class="reason" maxlength="200" show-word-limit placeholder="驳回原因（可选，仅管理端可见）"
                data-testid="request-reject-reason" />
    </ConfirmDialog>
  </div>
</template>

<script>
import { api } from '@/api'
import { REQUEST_STATUS_OPTIONS, canHandleRequest, operatorName } from '@/utils/license'
import { formatTime } from '@/utils/time'
import RequestIssueDialog from '@/components/request/RequestIssueDialog.vue'

export default {
  name: 'RequestList',
  components: { RequestIssueDialog },
  data() {
    return {
      status: 'pending', items: [], total: 0, page: 1, pageSize: 20, loading: false,
      statusOptions: REQUEST_STATUS_OPTIONS,
      current: null, issueVisible: false, rejectVisible: false, rejecting: false, reason: ''
    }
  },
  watch: {
    page() { this.load() },
    pageSize() { this.page = 1; this.load() }
  },
  created() { this.load() },
  methods: {
    fmt: formatTime,
    canHandle: row => canHandleRequest(row.status),
    handler: row => operatorName(row.handled_by_username, row.handled_by) || '-',
    shortCode: c => (c && c.length > 28 ? c.slice(0, 26) + '…' : c),
    async load() {
      this.loading = true
      try {
        const res = await api.requests.list({ status: this.status || undefined, page: this.page, page_size: this.pageSize })
        this.items = res.items
        this.total = res.total
      } catch (e) { /* 拦截器已提示 */ } finally { this.loading = false }
      this.$store.dispatch('refreshPending')
    },
    search() { this.page === 1 ? this.load() : (this.page = 1) },
    openIssue(row) { this.current = row; this.issueVisible = true },
    openReject(row) { this.current = row; this.reason = ''; this.rejectVisible = true },
    onHandled() { this.load() },
    async doReject() {
      this.rejecting = true
      try {
        await api.requests.reject(this.current.id, this.reason.trim())
        this.rejectVisible = false
        this.$message.success('已驳回')
        this.load()
      } catch (e) {
        if (e.code === 'REQUEST_NOT_PENDING' || e.code === 'REQUEST_NOT_FOUND') { this.rejectVisible = false; this.load() }
      } finally { this.rejecting = false }
    }
  }
}
</script>

<style scoped>
.filters >>> .el-form-item { margin-bottom: 0; }
.danger-text, .danger-text:hover { color: var(--seal); }
.reason { margin-top: 8px; }
</style>
