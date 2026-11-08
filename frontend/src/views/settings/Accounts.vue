<template>
  <div class="page">
    <PageHeader title="视频账号" :subtitle="`每个账号每天可生成 ${dailyLimit} 条。登录状态以 cookie 保存在数据库里。`">
      <template #actions>
        <BaseButton variant="primary" @click="addVisible = true">添加账号</BaseButton>
      </template>
    </PageHeader>

    <div class="table-wrap">
      <el-table v-loading="loading" :data="list" empty-text="还没有视频账号。">
        <el-table-column prop="name" label="账号" min-width="150" />
        <el-table-column label="登录" width="90">
          <template slot-scope="{ row }">
            <StatusText :status="row.logged_in ? 'logged_in' : 'logged_out'" />
          </template>
        </el-table-column>
        <el-table-column label="登录有效期" width="120">
          <template slot-scope="{ row }">
            <StatusText :status="cookieStatus(row.cookie_days)" :n="row.cookie_days" />
          </template>
        </el-table-column>
        <el-table-column label="今日用量" width="100">
          <template slot-scope="{ row }">{{ usageOf(row) }} / {{ dailyLimit }}</template>
        </el-table-column>
        <el-table-column label="启用" width="80">
          <template slot-scope="{ row }">
            <el-switch v-model="row.enabled" :aria-label="`启用 ${row.name}`" @change="toggle(row)" />
          </template>
        </el-table-column>
        <el-table-column label="操作" min-width="240">
          <template slot-scope="{ row }">
            <BaseButton variant="text" :loading="busyId === row.id" @click="checkLogin(row)">{{ row.logged_in ? '刷新状态' : '登录' }}</BaseButton>
            <BaseButton variant="text" @click="launch(row)">打开</BaseButton>
            <BaseButton variant="text" @click="rename(row)">重命名</BaseButton>
            <BaseButton variant="text" @click="remove(row)">删除</BaseButton>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-dialog append-to-body title="添加账号" :visible.sync="addVisible" width="440px" @closed="newName = ''">
      <form class="form-stack" novalidate @submit.prevent="add">
        <FormField label="账号名称" required>
          <el-input v-model.trim="newName" placeholder="如：豆包小号 2" />
        </FormField>
      </form>
      <template #footer>
        <BaseButton variant="text" @click="addVisible = false">取消</BaseButton>
        <BaseButton variant="primary" :loading="adding" @click="add">添加</BaseButton>
      </template>
    </el-dialog>
  </div>
</template>

<script>
import { api } from '@/api'
import { cookieStatus } from '@/components/base/status'
import { confirmDelete, promptText } from '@/utils/dialogs'

export default {
  name: 'AccountsSettings',
  data() {
    return {
      list: [],
      dailyLimit: 2,
      loading: false,
      busyId: '',
      addVisible: false,
      adding: false,
      newName: ''
    }
  },
  created() {
    this.load()
  },
  methods: {
    cookieStatus,
    usageOf(row) {
      return row.usage ? row.usage.count || 0 : 0
    },
    async load() {
      this.loading = true
      try {
        const res = await api.video.listAccounts()
        const d = (res && res.data) || res || {}
        this.list = Array.isArray(d) ? d : (d.accounts || [])
        if (d.daily_limit) this.dailyLimit = d.daily_limit
      } catch (e) {
        this.list = []
      } finally {
        this.loading = false
      }
    },
    async toggle(row) {
      try {
        await api.video.updateAccount(row.id, { enabled: row.enabled })
        this.$message.success(row.enabled ? `已启用 ${row.name}` : `已停用 ${row.name}`)
      } catch (e) {
        row.enabled = !row.enabled
      }
    },
    async checkLogin(row) {
      this.busyId = row.id
      try {
        await api.video.checkLogin(row.id)
        this.$message.success('已刷新')
        this.load()
      } catch (e) {
        // 拦截器已提示
      } finally {
        this.busyId = ''
      }
    },
    async launch(row) {
      try {
        await api.video.launchDoubao(row.id)
        this.$message.success('已在 Chrome 打开豆包页面')
      } catch (e) { /* 拦截器已提示 */ }
    },
    async rename(row) {
      const name = await promptText('新的账号名称', '重命名', row.name)
      if (!name || name === row.name) return
      try {
        await api.video.renameAccount(row.id, name)
        this.$message.success('已重命名')
        this.load()
      } catch (e) { /* 拦截器已提示 */ }
    },
    async remove(row) {
      if (!(await confirmDelete(`删除账号“${row.name}”？`))) return
      try {
        await api.video.deleteAccount(row.id)
        this.$message.success('已删除')
        this.load()
      } catch (e) { /* 拦截器已提示 */ }
    },
    async add() {
      if (!this.newName) {
        this.$message.warning('请填写账号名称')
        return
      }
      this.adding = true
      try {
        await api.video.addAccount({ name: this.newName })
        this.$message.success('已添加')
        this.addVisible = false
        this.load()
      } catch (e) {
        // 拦截器已提示
      } finally {
        this.adding = false
      }
    }
  }
}
</script>
