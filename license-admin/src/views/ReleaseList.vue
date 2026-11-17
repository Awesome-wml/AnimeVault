<template>
  <div class="page">
    <PageHeader title="版本发布" subtitle="管理客户端安装包：草稿 → 发布 → 撤回。强制升级线以下的客户端无法激活或续租。">
      <template slot="actions">
        <el-button v-if="canWrite" type="primary" icon="el-icon-plus" data-testid="release-new" @click="openForm(null)">新建版本</el-button>
      </template>
    </PageHeader>

    <el-form inline class="filters" @submit.native.prevent="search">
      <el-form-item>
        <el-select v-model="channel" placeholder="全部渠道" clearable style="width: 150px" data-testid="release-filter-channel" @change="search">
          <el-option v-for="c in channels" :key="c.value" :label="c.label" :value="c.value" />
        </el-select>
      </el-form-item>
      <el-form-item>
        <el-select v-model="platform" placeholder="全部平台" clearable style="width: 170px" data-testid="release-filter-platform" @change="search">
          <el-option v-for="p in platforms" :key="p.value" :label="p.label" :value="p.value" />
        </el-select>
      </el-form-item>
      <el-form-item>
        <el-select v-model="status" placeholder="全部状态" clearable style="width: 140px" data-testid="release-filter-status" @change="search">
          <el-option v-for="s in statusOptions" :key="s.value" :label="s.label" :value="s.value" />
        </el-select>
      </el-form-item>
      <el-form-item><el-button @click="load">刷新</el-button></el-form-item>
    </el-form>

    <BaseTable :data="items" :loading="loading" :total="total" :page.sync="page" :page-size.sync="pageSize"
               empty-text="还没有版本记录" data-testid="release-table">
      <el-table-column label="版本" min-width="130">
        <template slot-scope="{ row }"><b class="mono" :data-testid="'rel-version-' + row.id">{{ row.version }}</b></template>
      </el-table-column>
      <el-table-column label="渠道" width="90"><template slot-scope="{ row }">{{ row.channel }}</template></el-table-column>
      <el-table-column label="平台" width="110"><template slot-scope="{ row }">{{ row.platform }}</template></el-table-column>
      <el-table-column label="状态" width="100">
        <template slot-scope="{ row }"><StatusTag kind="release" :status="row.status" /></template>
      </el-table-column>
      <el-table-column label="强制升级线" width="120">
        <template slot-scope="{ row }"><span class="mono small">{{ row.min_supported || '-' }}</span></template>
      </el-table-column>
      <el-table-column label="发布时间" width="140"><template slot-scope="{ row }">{{ row.published_at ? fmt(row.published_at) : '-' }}</template></el-table-column>
      <el-table-column label="操作" width="190">
        <template slot-scope="{ row }">
          <span class="inline-actions">
            <el-button type="text" :data-testid="'rel-detail-' + row.id" @click="openDrawer(row)">详情</el-button>
            <template v-if="canWrite">
              <el-button v-if="acts(row).edit" type="text" :data-testid="'rel-edit-' + row.id" @click="openForm(row)">编辑</el-button>
              <el-button v-if="acts(row).publish" type="text" :data-testid="'rel-publish-' + row.id" @click="askPublish(row)">发布</el-button>
              <el-button v-if="acts(row).withdraw" type="text" class="danger-text" :data-testid="'rel-withdraw-' + row.id" @click="askWithdraw(row)">撤回</el-button>
            </template>
          </span>
        </template>
      </el-table-column>
    </BaseTable>

    <ReleaseFormDialog :visible.sync="formVisible" :release="current" @saved="load" />
    <ReleaseDrawer ref="drawer" :visible.sync="drawerVisible" :release-id="drawerId" @action="onDrawerAction" />

    <ConfirmDialog :visible.sync="publishVisible" title="发布版本" confirm-label="确认发布" :loading="acting" @confirm="doPublish">
      <p>确认发布 <b class="mono">{{ current && current.version }}</b>（{{ current && current.channel }} / {{ current && current.platform }}）？
        发布后客户端立即能检查到该版本，且版本号、下载地址、sha256 不可再改。</p>
      <p v-if="current && current.min_supported" class="note note--warn">该版本带强制升级线 {{ current.min_supported }}：发布后低于它的客户端将被要求升级。</p>
    </ConfirmDialog>
    <ConfirmDialog :visible.sync="withdrawVisible" title="撤回版本" confirm-label="确认撤回" danger :loading="acting" @confirm="doWithdraw">
      <p>确认撤回 <b class="mono">{{ current && current.version }}</b>（{{ current && current.channel }} / {{ current && current.platform }}）？
        撤回后客户端不再收到该版本，且不可恢复，需要重发请新建草稿。</p>
      <p v-if="current && current.min_supported" class="note note--warn">该版本提供了强制升级线 {{ current.min_supported }}，撤回后强制升级线可能随之降低。</p>
    </ConfirmDialog>
  </div>
</template>

<script>
import { api } from '@/api'
import { can } from '@/config/roles'
import { CHANNELS, PLATFORMS } from '@/config/releases'
import { RELEASE_STATUS_OPTIONS, releaseActions, releaseNotice } from '@/utils/release'
import { formatTime } from '@/utils/time'
import ReleaseDrawer from '@/components/release/ReleaseDrawer.vue'
import ReleaseFormDialog from '@/components/release/ReleaseFormDialog.vue'

export default {
  name: 'ReleaseList',
  components: { ReleaseDrawer, ReleaseFormDialog },
  data() {
    return {
      channel: '', platform: '', status: '', items: [], total: 0, page: 1, pageSize: 20, loading: false,
      channels: CHANNELS, platforms: PLATFORMS, statusOptions: RELEASE_STATUS_OPTIONS,
      current: null, formVisible: false, drawerVisible: false, drawerId: '',
      publishVisible: false, withdrawVisible: false, acting: false
    }
  },
  computed: {
    canWrite() { return can(this.$store.getters.role, 'release.write') }
  },
  watch: {
    page() { this.load() },
    pageSize() { this.page = 1; this.load() }
  },
  created() { this.load() },
  methods: {
    fmt: formatTime,
    acts: row => releaseActions(row.status),
    async load() {
      this.loading = true
      try {
        const res = await api.releases.list({
          channel: this.channel || undefined, platform: this.platform || undefined, status: this.status || undefined,
          page: this.page, page_size: this.pageSize
        })
        this.items = res.items
        this.total = res.total
      } catch (e) { /* 拦截器已提示 */ } finally { this.loading = false }
    },
    search() { this.page === 1 ? this.load() : (this.page = 1) },
    openForm(row) { this.current = row; this.formVisible = true },
    openDrawer(row) { this.drawerId = row.id; this.drawerVisible = true },
    askPublish(row) { this.current = row; this.publishVisible = true },
    askWithdraw(row) { this.current = row; this.withdrawVisible = true },
    onDrawerAction(action, row) {
      this.drawerVisible = false
      if (action === 'edit') this.openForm(row)
      else if (action === 'publish') this.askPublish(row)
      else if (action === 'withdraw') this.askWithdraw(row)
    },
    async doPublish() { await this.run(() => api.releases.publish(this.current.id), '已发布', () => { this.publishVisible = false }) },
    async doWithdraw() { await this.run(() => api.releases.withdraw(this.current.id), '已撤回', () => { this.withdrawVisible = false }) },
    async run(fn, okText, close) {
      this.acting = true
      try {
        const res = await fn()
        close()
        this.$message.success(okText)
        const notice = releaseNotice(res)
        if (notice) this.$message({ type: 'warning', message: notice, duration: 10000, showClose: true, customClass: 'release-notice' })
        this.load()
      } catch (e) {
        // 拦截器已提示；状态冲突时关闭弹窗并刷新
        if (e.code === 'INVALID_TRANSITION' || e.code === 'RELEASE_NOT_FOUND') { close(); this.load() }
      } finally { this.acting = false }
    }
  }
}
</script>

<style scoped>
.filters >>> .el-form-item { margin-bottom: 0; }
.danger-text, .danger-text:hover { color: var(--seal); }
</style>
