<template>
  <div class="page">
    <PageHeader title="审计日志" subtitle="所有管理操作的记录，只读、不可修改。敏感字段（授权码、密码等）已由服务端剔除。" />

    <el-form inline class="filters" @submit.native.prevent="search">
      <el-form-item>
        <el-select v-model="filters.action" placeholder="全部操作" clearable filterable style="width: 190px" data-testid="audit-action" @change="search">
          <el-option v-for="a in actions" :key="a" :label="actionText(a)" :value="a"><span>{{ actionText(a) }}</span><span class="muted caption mono"> {{ a }}</span></el-option>
        </el-select>
      </el-form-item>
      <el-form-item>
        <el-select v-if="isSuper" v-model="filters.admin_id" placeholder="全部管理员" clearable style="width: 170px" data-testid="audit-admin" @change="search">
          <el-option v-for="a in adminList" :key="a.id" :label="a.username" :value="a.id" />
        </el-select>
        <el-input v-else v-model="filters.admin_id" placeholder="管理员 ID" clearable style="width: 190px" @keyup.enter.native="search" />
      </el-form-item>
      <el-form-item><el-button type="primary" @click="search">查询</el-button><el-button @click="reset">重置</el-button></el-form-item>
    </el-form>

    <BaseTable :data="items" :loading="loading" :total="total" :page.sync="page" :page-size.sync="pageSize" empty-text="没有审计记录">
      <el-table-column label="时间" width="140"><template slot-scope="{ row }">{{ fmt(row.at) }}</template></el-table-column>
      <el-table-column label="管理员" width="110" show-overflow-tooltip><template slot-scope="{ row }"><span :data-testid="'audit-operator-' + row.seq">{{ adminName(row) }}</span></template></el-table-column>
      <el-table-column label="操作" width="130">
        <template slot-scope="{ row }">{{ actionText(row.action) }}<div class="cell-sub mono">{{ row.action }}</div></template>
      </el-table-column>
      <el-table-column label="对象" min-width="150" show-overflow-tooltip><template slot-scope="{ row }"><span class="mono small">{{ row.target }}</span></template></el-table-column>
      <el-table-column label="IP" width="110" prop="ip" />
      <el-table-column label="变更" min-width="150">
        <template slot-scope="{ row }">
          <JsonFold v-if="row.before" :value="row.before" label="变更前" />
          <JsonFold v-if="row.after" :value="row.after" label="变更后" />
          <span v-if="!row.before && !row.after" class="muted">-</span>
        </template>
      </el-table-column>
    </BaseTable>
  </div>
</template>

<script>
import { api } from '@/api'
import { can } from '@/config/roles'
import { AUDIT_ACTIONS, AUDIT_ACTION_LABELS, operatorName } from '@/utils/license'
import { formatTime } from '@/utils/time'

export default {
  name: 'AuditLog',
  data() {
    return {
      filters: { action: '', admin_id: '' }, items: [], total: 0, page: 1, pageSize: 20, loading: false,
      actions: AUDIT_ACTIONS, adminList: []
    }
  },
  computed: { isSuper() { return can(this.$store.getters.role, 'admin.manage') } },
  watch: {
    page() { this.load() },
    pageSize() { this.page = 1; this.load() }
  },
  async created() {
    if (this.isSuper) { try { this.adminList = (await api.admins.list({ page: 1, page_size: 100 })).items } catch (e) { /* 已提示 */ } }
    this.load()
  },
  methods: {
    fmt: formatTime,
    actionText: a => AUDIT_ACTION_LABELS[a] || a,
    /** 优先用审计记录里冗余的用户名；历史记录没有就查管理员列表，再不行显示 id 前 8 位 */
    adminName(row) {
      if (!row.admin_id && !row.admin_username) return '系统/匿名'
      const a = this.adminList.find(x => x.id === row.admin_id)
      return operatorName(row.admin_username || (a && a.username), row.admin_id)
    },
    async load() {
      this.loading = true
      try {
        const res = await api.audit.list({
          action: this.filters.action || undefined, admin_id: (this.filters.admin_id || '').trim() || undefined,
          page: this.page, page_size: this.pageSize
        })
        this.items = res.items
        this.total = res.total
      } catch (e) { /* 已提示 */ } finally { this.loading = false }
    },
    search() { this.page === 1 ? this.load() : (this.page = 1) },
    reset() { this.filters = { action: '', admin_id: '' }; this.search() }
  }
}
</script>

<style scoped>
.filters >>> .el-form-item { margin-bottom: 0; }
</style>
