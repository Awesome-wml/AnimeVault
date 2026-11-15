<template>
  <div class="page">
    <PageHeader title="管理员管理" subtitle="仅超级管理员可见。管理员账号与用户账号分开。">
      <el-button slot="actions" type="primary" icon="el-icon-plus" data-testid="open-create-admin" @click="createVisible = true">新建管理员</el-button>
    </PageHeader>

    <BaseTable :data="items" :loading="loading">
      <el-table-column label="用户名" min-width="140" prop="username">
        <template slot-scope="{ row }">{{ row.username }}<span v-if="isSelf(row)" class="muted small">（当前）</span></template>
      </el-table-column>
      <el-table-column label="角色" width="130"><template slot-scope="{ row }">{{ roleText(row.role) }}</template></el-table-column>
      <el-table-column label="状态" width="90">
        <template slot-scope="{ row }"><span :class="row.enabled ? 'ok' : 'off'">{{ row.enabled ? '启用' : '已禁用' }}</span></template>
      </el-table-column>
      <el-table-column label="创建时间" width="150"><template slot-scope="{ row }">{{ fmt(row.created_at) }}</template></el-table-column>
      <el-table-column label="最近登录" width="150"><template slot-scope="{ row }">{{ row.last_login_at ? fmt(row.last_login_at) : '从未登录' }}</template></el-table-column>
      <el-table-column label="操作" width="260">
        <template slot-scope="{ row }">
          <span class="inline-actions">
            <el-button size="mini" :disabled="isSelf(row)" :title="isSelf(row) ? '不能修改自己的角色' : ''" @click="edit(row, 'role')">改角色</el-button>
            <el-button size="mini" @click="edit(row, 'password')">重置密码</el-button>
            <el-button size="mini" :type="row.enabled ? 'danger' : ''" :disabled="isSelf(row)" :title="isSelf(row) ? '不能禁用自己' : ''"
                       @click="toggle(row)">{{ row.enabled ? '禁用' : '启用' }}</el-button>
          </span>
        </template>
      </el-table-column>
    </BaseTable>

    <AdminCreateDialog :visible.sync="createVisible" @saved="load" />
    <AdminEditDialog :visible.sync="editVisible" :mode="editMode" :admin="editing" @saved="load" />
  </div>
</template>

<script>
import { api } from '@/api'
import { roleLabel } from '@/config/roles'
import { formatTime } from '@/utils/time'
import AdminCreateDialog from '@/components/admin/AdminCreateDialog.vue'
import AdminEditDialog from '@/components/admin/AdminEditDialog.vue'

export default {
  name: 'AdminList',
  components: { AdminCreateDialog, AdminEditDialog },
  data() {
    return { items: [], loading: false, createVisible: false, editVisible: false, editMode: 'role', editing: null }
  },
  created() { this.load() },
  methods: {
    fmt: formatTime,
    roleText: roleLabel,
    isSelf(row) { return this.$store.state.admin && row.id === this.$store.state.admin.id },
    async load() {
      this.loading = true
      try { this.items = (await api.admins.list()).items } catch (e) { /* 已提示 */ } finally { this.loading = false }
    },
    edit(row, mode) { this.editing = row; this.editMode = mode; this.editVisible = true },
    async toggle(row) {
      if (row.enabled) {
        try {
          await this.$confirm(`禁用后 ${row.username} 将立即无法登录，已登录的会话也会失效。确认禁用？`, '禁用管理员', { type: 'warning', confirmButtonText: '确认禁用', cancelButtonText: '取消' })
        } catch (e) { return }
      }
      try {
        await api.admins.update(row.id, { enabled: !row.enabled })
        this.$message.success(row.enabled ? '已禁用' : '已启用')
        this.load()
      } catch (e) { /* 如 LAST_SUPER，拦截器已提示 */ }
    }
  }
}
</script>

<style scoped>
.ok { color: var(--ok); }
.off { color: var(--seal); }
</style>
