<template>
  <div class="page">
    <PageHeader title="授权管理" subtitle="签发、查看和管理授权">
      <el-button v-if="canWrite" slot="actions" type="primary" icon="el-icon-plus" data-testid="open-issue" @click="issueVisible = true">签发授权</el-button>
    </PageHeader>

    <div class="toolbar">
      <el-form inline class="filters" @submit.native.prevent="search">
        <el-form-item>
          <el-select v-model="filters.status" placeholder="全部状态" clearable style="width: 130px" data-testid="filter-status" @change="search">
            <el-option v-for="s in statusOptions" :key="s.value" :label="s.label" :value="s.value" />
          </el-select>
        </el-form-item>
        <el-form-item><el-input v-model="filters.email" placeholder="邮箱" clearable style="width: 190px" data-testid="filter-email" @keyup.enter.native="search" /></el-form-item>
        <el-form-item><el-input v-model="filters.lid" placeholder="授权 ID（lid）" clearable style="width: 190px" data-testid="filter-lid" @keyup.enter.native="search" /></el-form-item>
        <el-form-item>
          <el-button type="primary" data-testid="search" @click="search">查询</el-button>
          <el-button @click="reset">重置</el-button>
        </el-form-item>
      </el-form>
    </div>

    <BaseTable :data="items" :loading="loading" :total="total" :page.sync="page" :page-size.sync="pageSize"
               empty-text="没有符合条件的授权" data-testid="license-table">
      <el-table-column label="授权 ID" width="158">
        <template slot-scope="{ row }">
          <el-button type="text" class="mono lid-link" :data-testid="'lid-' + row.lid" @click="openDrawer(row)">{{ row.lid }}</el-button>
        </template>
      </el-table-column>
      <el-table-column label="邮箱" min-width="150" show-overflow-tooltip>
        <template slot-scope="{ row }">{{ row.email || '-' }}</template>
      </el-table-column>
      <el-table-column label="套餐" width="64"><template slot-scope="{ row }">{{ planText(row.plan) }}</template></el-table-column>
      <el-table-column label="状态" width="100"><template slot-scope="{ row }"><StatusTag :status="row.status" /></template></el-table-column>
      <el-table-column label="到期时间" width="116">
        <template slot-scope="{ row }">
          <span :class="'expiry--' + level(row)" :title="level(row) === 'soon' ? '7 天内到期' : ''">{{ fmt(row.expires_at, false) }}</span>
          <span v-if="level(row) === 'soon'" class="expiry-flag">临近</span>
        </template>
      </el-table-column>
      <el-table-column label="最近在线" width="132"><template slot-scope="{ row }"><span :class="{ muted: !row.last_seen_at }">{{ seen(row) }}</span></template></el-table-column>
      <el-table-column label="创建时间" width="132"><template slot-scope="{ row }">{{ fmt(row.issued_at) }}</template></el-table-column>
      <el-table-column v-if="canWrite" label="操作" width="176" fixed="right">
        <template slot-scope="{ row }">
          <LicenseActionButtons :status="row.status" :only="rowActions(row)" @action="a => host(a, row)" />
        </template>
      </el-table-column>
    </BaseTable>

    <IssueDialog :visible.sync="issueVisible" @issued="onChanged" />
    <LicenseDrawer ref="drawer" :visible.sync="drawerVisible" :lid="currentLid" @action="host" />
    <LicenseActionHost ref="host" @done="onDone" />
  </div>
</template>

<script>
import { api } from '@/api'
import { can } from '@/config/roles'
import { planLabel } from '@/config/plans'
import { STATUS_OPTIONS, expiryLevel, lastSeenText } from '@/utils/license'
import { formatTime } from '@/utils/time'
import IssueDialog from '@/components/license/IssueDialog.vue'
import LicenseDrawer from '@/components/license/LicenseDrawer.vue'
import LicenseActionButtons from '@/components/license/LicenseActionButtons.vue'
import LicenseActionHost from '@/components/license/LicenseActionHost.vue'

export default {
  name: 'LicenseList',
  components: { IssueDialog, LicenseDrawer, LicenseActionButtons, LicenseActionHost },
  data() {
    return {
      filters: { status: '', email: '', lid: '' },
      items: [], total: 0, page: 1, pageSize: 20, loading: false,
      statusOptions: STATUS_OPTIONS,
      issueVisible: false, drawerVisible: false, currentLid: ''
    }
  },
  computed: {
    canWrite() { return can(this.$store.getters.role, 'license.write') }
  },
  watch: {
    page() { this.load() },
    pageSize() { this.page = 1; this.load() }
  },
  created() { this.load() },
  methods: {
    fmt: formatTime,
    planText: planLabel,
    level(row) { return expiryLevel(row.expires_at, row.status) },
    seen(row) { return lastSeenText(row, formatTime) },
    /** 行内只显示与当前状态相关的那一个：正常可停用，已停用可恢复 */
    rowActions(row) { return ['extend', row.status === 'suspended' ? 'resume' : 'suspend', 'revoke'] },
    async load() {
      this.loading = true
      try {
        const f = this.filters
        const res = await api.licenses.list({
          status: f.status || undefined, email: f.email.trim() || undefined, lid: f.lid.trim() || undefined,
          page: this.page, page_size: this.pageSize
        })
        this.items = res.items
        this.total = res.total
      } catch (e) { /* 拦截器已提示 */ } finally {
        this.loading = false
      }
    },
    search() { this.page === 1 ? this.load() : (this.page = 1) },
    reset() { this.filters = { status: '', email: '', lid: '' }; this.search() },
    openDrawer(row) {
      this.currentLid = row.lid
      this.drawerVisible = true
    },
    host(action, lic) { this.$refs.host.start(action, lic) },
    onChanged() { this.load() },
    onDone() {
      this.load()
      if (this.drawerVisible) this.$refs.drawer.load()
    }
  }
}
</script>

<style scoped>
.filters >>> .el-form-item { margin-bottom: 0; }
.lid-link { font-size: 12px; padding: 0; min-height: 0; }
.expiry--soon, .expiry--expired { color: var(--soon); font-weight: 600; }
.expiry-flag { margin-left: 4px; font-size: 11px; padding: 0 5px; border: 1px solid var(--soon); border-radius: 4px; color: var(--soon); }
</style>
