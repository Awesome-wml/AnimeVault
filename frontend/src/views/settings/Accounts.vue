<template>
  <div class="page">
    <PageHeader title="视频账号" :subtitle="`会员账号按豆包额度计算（检查登录、生成视频时自动读取）；非会员或额度读取失败时每天 ${dailyLimit} 条。登录状态以 cookie 保存在数据库里。`">
      <template #actions>
        <BaseButton variant="primary" @click="addVisible = true">添加账号</BaseButton>
      </template>
    </PageHeader>

    <div class="table-wrap">
      <el-table v-loading="loading" :data="list" empty-text="还没有视频账号。">
        <el-table-column prop="name" label="账号" min-width="150" />
        <el-table-column label="类型" width="110">
          <template slot-scope="{ row }">
            <StatusText :status="row.account_type === 'member' ? 'type_member' : 'type_free'" />
          </template>
        </el-table-column>
        <el-table-column label="登录" width="110">
          <template slot-scope="{ row }">
            <StatusText :status="loginStatus(row)" />
          </template>
        </el-table-column>
        <el-table-column label="登录有效期" width="120">
          <template slot-scope="{ row }">
            <StatusText :status="cookieStatus(row.cookie_days)" :n="row.cookie_days" />
          </template>
        </el-table-column>
        <el-table-column label="额度" min-width="260">
          <template slot-scope="{ row }">
            <StatusText :status="quotaStatus(row, dailyLimit).key" :n="quotaStatus(row, dailyLimit).vars" />
          </template>
        </el-table-column>
        <el-table-column label="代理" width="130">
          <template slot-scope="{ row }">
            <span :class="{ 'proxy-off': !row.proxy || !row.proxy.server }">{{ proxyLabel(row) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="启用" width="80">
          <template slot-scope="{ row }">
            <el-switch v-model="row.enabled" :aria-label="`启用 ${row.name}`" @change="toggle(row)" />
          </template>
        </el-table-column>
        <el-table-column label="操作" min-width="280">
          <template slot-scope="{ row }">
            <BaseButton variant="text" :loading="busyId === row.id" @click="checkLogin(row)">{{ checkLabel(row) }}</BaseButton>
            <BaseButton variant="text" @click="launch(row)">打开</BaseButton>
            <BaseButton variant="text" @click="changeType(row)">{{ row.account_type === 'member' ? '转免费' : '转会员' }}</BaseButton>
            <BaseButton variant="text" @click="openProxy(row)">代理</BaseButton>
            <BaseButton variant="text" @click="rename(row)">重命名</BaseButton>
            <BaseButton variant="text" @click="remove(row)">删除</BaseButton>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-dialog append-to-body title="添加账号" :visible.sync="addVisible" width="440px" @closed="resetNew">
      <form class="form-stack" novalidate @submit.prevent="add">
        <FormField label="账号名称" required>
          <el-input v-model.trim="newName" placeholder="如：豆包小号 2" />
        </FormField>
        <FormField label="账号类型" required>
          <el-select v-model="newType" placeholder="选择账号类型" style="width: 100%">
            <el-option label="额度会员（按套餐额度）" value="member" />
            <el-option label="免费（每日 2 条）" value="free" />
          </el-select>
        </FormField>
        <FormField label="代理服务器（可选）">
          <el-input v-model.trim="newProxy.server" placeholder="http://host:port 或 socks5://host:port，留空直连" />
        </FormField>
        <FormField label="代理用户名（可选）">
          <el-input v-model.trim="newProxy.username" placeholder="无认证可留空" />
        </FormField>
        <FormField label="代理密码（可选）">
          <el-input v-model="newProxy.password" type="password" show-password placeholder="无认证可留空" />
        </FormField>
      </form>
      <template #footer>
        <BaseButton variant="text" @click="addVisible = false">取消</BaseButton>
        <BaseButton variant="primary" :loading="adding" @click="add">添加</BaseButton>
      </template>
    </el-dialog>

    <el-dialog append-to-body :title="`代理设置 · ${editingProxy ? editingProxy.name : ''}`" :visible.sync="proxyVisible" width="440px">
      <form class="form-stack" novalidate @submit.prevent="saveProxy">
        <FormField label="代理服务器">
          <el-input v-model.trim="proxyForm.server" placeholder="http://host:port 或 socks5://host:port，留空直连" />
        </FormField>
        <FormField label="代理用户名">
          <el-input v-model.trim="proxyForm.username" placeholder="无认证可留空" />
        </FormField>
        <FormField label="代理密码">
          <el-input v-model="proxyForm.password" type="password" show-password placeholder="无认证可留空" />
        </FormField>
      </form>
      <template #footer>
        <BaseButton variant="text" @click="proxyVisible = false">取消</BaseButton>
        <BaseButton variant="primary" :loading="proxySaving" @click="saveProxy">保存</BaseButton>
      </template>
    </el-dialog>
  </div>
</template>

<script>
import { api } from '@/api'
import { cookieStatus, loginStatus, quotaStatus } from '@/components/base/status'
import { confirmDelete, promptText } from '@/utils/dialogs'
import { toastError, toastSuccess, toastWarning } from '@/utils/notify'

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
      newName: '',
      newType: 'free',
      newProxy: { server: '', username: '', password: '' },
      proxyVisible: false,
      proxySaving: false,
      editingProxy: null,
      proxyForm: { server: '', username: '', password: '' }
    }
  },
  created() {
    this.load()
  },
  methods: {
    cookieStatus,
    loginStatus,
    checkLabel(row) {
      // 需重新检查（标记已登录但没有 cookie / 上次检查出错）要让人看得见“重新检查”
      const st = loginStatus(row)
      if (st === 'need_recheck') return '重新检查'
      return st === 'logged_in' ? '刷新状态' : '登录'
    },
    quotaStatus,
    proxyLabel(row) {
      const p = row.proxy
      if (!p || !p.server) return '直连'
      const host = String(p.server).replace(/^\w+:\/\//, '')
      return p.username ? `${host}（认证）` : host
    },
    openProxy(row) {
      this.editingProxy = row
      this.proxyForm = {
        server: (row.proxy && row.proxy.server) || '',
        username: (row.proxy && row.proxy.username) || '',
        password: (row.proxy && row.proxy.password) || ''
      }
      this.proxyVisible = true
    },
    async saveProxy() {
      if (!this.editingProxy) return
      this.proxySaving = true
      try {
        await api.video.updateAccount(this.editingProxy.id, { proxy: this.proxyForm })
        this.$message.success('代理已保存')
        this.proxyVisible = false
        this.load()
      } catch (e) {
        toastError(e)
      } finally {
        this.proxySaving = false
      }
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
        const res = await api.video.checkLogin(row.id)
        const ok = res && res.data && res.data.logged_in
        const msg = (res && res.message) || '已刷新'
        if (ok) toastSuccess(msg)
        else toastWarning(msg)
      } catch (e) {
        toastError(e)
      } finally {
        this.busyId = ''
        this.load()
      }
    },
    async launch(row) {
      try {
        const res = await api.video.launchDoubao(row.id)
        toastSuccess((res && res.message) || '已在 Chrome 打开豆包页面')
      } catch (e) { toastError(e) }
    },
    async rename(row) {
      const name = await promptText('新的账号名称', '重命名', row.name)
      if (!name || name === row.name) return
      try {
        await api.video.renameAccount(row.id, name)
        this.$message.success('已重命名')
        this.load()
      } catch (e) { toastError(e) }
    },
    async changeType(row) {
      const next = row.account_type === 'member' ? 'free' : 'member'
      const label = next === 'member' ? '额度会员' : '免费'
      try {
        await api.video.setAccountType(row.id, next)
        this.$message.success(`已切换为${label}账号`)
        this.load()
      } catch (e) { toastError(e) }
    },
    resetNew() {
      this.newName = ''
      this.newType = 'free'
      this.newProxy = { server: '', username: '', password: '' }
    },
    async remove(row) {
      if (!(await confirmDelete(`删除账号“${row.name}”？`))) return
      try {
        await api.video.deleteAccount(row.id)
        this.$message.success('已删除')
        this.load()
      } catch (e) { toastError(e) }
    },
    async add() {
      if (!this.newName) {
        this.$message.warning('请填写账号名称')
        return
      }
      this.adding = true
      try {
        await api.video.addAccount({ name: this.newName, account_type: this.newType, proxy: this.newProxy })
        this.$message.success('已添加')
        this.addVisible = false
        this.load()
      } catch (e) {
        toastError(e)
      } finally {
        this.adding = false
      }
    }
  }
}
</script>

<style scoped>
.proxy-off {
  color: #909399;
}
</style>
