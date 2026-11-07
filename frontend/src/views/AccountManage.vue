<template>
  <div class="account-manage" style="padding:20px">
    <div style="display:flex;align-items:center;gap:12px;margin-bottom:20px">
      <el-button icon="el-icon-back" size="small" @click="$router.back()"
        style="background:rgba(255,255,255,0.08);border-color:rgba(255,255,255,0.15);color:#ddd">返回</el-button>
      <h2 style="margin:0">账号管理</h2>
      <el-button type="primary" size="small" @click="showAdd = true">添加账号</el-button>
    </div>

    <el-alert type="info" :closable="false" style="margin-bottom:16px">
      登录态以 cookie 形式保存在数据库，不占用本地目录。每个账号每天限额 {{ dailyLimit }} 条。
    </el-alert>

    <el-table :data="accountList" size="small" v-loading="loading"
      :header-cell-style="{background:'#1a1a2e',color:'#aaa'}"
      :cell-style="{background:'#16162a',color:'#ddd'}">
      <el-table-column prop="name" label="账号名称" width="120"></el-table-column>
      <el-table-column label="登录状态" width="80" align="center">
        <template slot-scope="s">
          <el-tag v-if="s.row.logged_in" type="success" size="mini">已登录</el-tag>
          <el-tag v-else type="warning" size="mini">未登录</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="Cookie 有效期" width="110" align="center">
        <template slot-scope="s">
          <el-tag :type="cookieTag(s.row.cookie_days).type" size="mini">
            {{ cookieTag(s.row.cookie_days).text }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="今日用量" width="80" align="center">
        <template slot-scope="s">
          {{ s.row.usage ? s.row.usage.count : 0 }}/{{ dailyLimit }}
        </template>
      </el-table-column>
      <el-table-column label="启用" width="60" align="center">
        <template slot-scope="s">
          <el-switch v-model="s.row.enabled" @change="toggleAccount(s.row)"></el-switch>
        </template>
      </el-table-column>
      <el-table-column label="操作" min-width="200" align="center">
        <template slot-scope="s">
          <el-button size="mini" type="primary" @click="handleCheckLogin(s.row)">
            {{ s.row.logged_in ? '刷新' : '登录' }}
          </el-button>
          <el-button size="mini" type="warning" @click="renameAccount(s.row)">改名</el-button>
          <el-button size="mini" type="info" plain icon="el-icon-open" @click="handleLaunch(s.row)">打开豆包</el-button>
          <el-button size="mini" type="danger" plain @click="confirmDeleteAccount(s.row)">删</el-button>
        </template>
      </el-table-column>
    </el-table>

    <!-- 添加账号弹窗 -->
    <el-dialog title="添加账号" :visible.sync="showAdd" width="500px" :modal="false">
      <el-form :model="newAccount" label-width="100px" size="small">
        <el-form-item label="账号名称">
          <el-input v-model="newAccount.name" placeholder="如：豆包小号2"></el-input>
        </el-form-item>
      </el-form>
      <div slot="footer">
        <el-button @click="showAdd = false">取消</el-button>
        <el-button type="primary" :loading="adding" @click="handleAddAccount">添加</el-button>
      </div>
    </el-dialog>
  </div>
</template>

<script>
import { api } from '@/api'

export default {
  name: 'AccountManage',
  data() {
    return {
      accountList: [],
      loading: false,
      dailyLimit: 2,
      showAdd: false,
      adding: false,
      newAccount: { name: '' }
    }
  },
  created() {
    this.loadList()
  },
  methods: {
    cookieTag(days) {
      if (days === null || days === undefined) return { text: '未保存', type: 'info' }
      if (days <= 0) return { text: '已过期', type: 'danger' }
      if (days < 7) return { text: `剩 ${days} 天`, type: 'danger' }
      if (days < 14) return { text: `剩 ${days} 天`, type: 'warning' }
      return { text: `剩 ${days} 天`, type: 'success' }
    },
    async loadList() {
      this.loading = true
      try {
        const res = await api.video.listAccounts()
        if (Array.isArray(res)) {
          this.accountList = res
        } else if (res.accounts) {
          this.accountList = res.accounts
        } else if (res.data && res.data.accounts) {
          this.accountList = res.data.accounts
        } else if (res.data && Array.isArray(res.data)) {
          this.accountList = res.data
        }
      } catch (e) {
        console.error('加载账号失败:', e)
        this.$message.error('加载失败: ' + (e.response?.data?.detail || e.message))
      } finally {
        this.loading = false
      }
    },
    async toggleAccount(account) {
      try {
        await api.video.updateAccount(account.id, { enabled: account.enabled })
        this.$message.success(account.enabled ? `已启用 ${account.name}` : `已停用 ${account.name}`)
      } catch (e) {
        this.$message.error('操作失败')
      }
    },
    async handleCheckLogin(account) {
      try {
        await api.video.checkLogin(account.id)
        this.$message.success('已刷新')
        this.loadList()
      } catch (e) {
        this.$message.error('检查失败')
      }
    },
    async handleLaunch(account) {
      try {
        await api.video.launchDoubao(account.id)
        this.$message.success('已在 Chrome 打开豆包页面')
      } catch (e) {
        this.$message.error('打开失败: ' + (e.response?.data?.detail || e.message))
      }
    },
    async renameAccount(account) {
      const { value } = await this.$prompt('请输入新账号名称', '重命名', {
        inputValue: account.name,
        confirmButtonText: '确定',
        cancelButtonText: '取消'
      })
      if (value && value.trim()) {
        try {
          await api.video.renameAccount(account.id, value.trim())
          this.$message.success('已重命名')
          this.loadList()
        } catch (e) {
          this.$message.error('重命名失败')
        }
      }
    },
    confirmDeleteAccount(account) {
      this.$confirm(`确定删除账号 "${account.name}" 吗？`, '确认删除', {
        type: 'warning'
      }).then(async () => {
        await api.video.deleteAccount(account.id)
        this.$message.success('已删除')
        this.loadList()
      }).catch(() => {})
    },
    async handleAddAccount() {
      if (!this.newAccount.name.trim()) {
        this.$message.warning('请填写账号名称')
        return
      }
      this.adding = true
      try {
        await api.video.addAccount(this.newAccount)
        this.$message.success('已添加')
        this.showAdd = false
        this.newAccount = { name: '' }
        this.loadList()
      } catch (e) {
        this.$message.error('添加失败')
      } finally {
        this.adding = false
      }
    }
  }
}
</script>
