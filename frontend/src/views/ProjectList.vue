<template>
  <div class="project-list-container">
    <!-- 顶部导航栏 -->
    <div class="top-bar">
      <div class="logo-section">
        <div class="logo" @click="$router.push('/dashboard')">🎬 DongAI</div>
        <div class="tagline">AI短剧创作平台</div>
      </div>
      <div class="nav-actions">
        <el-button type="text" class="nav-btn" @click="showConfigDialog = true">
          <i class="el-icon-setting"></i> 配置API
        </el-button>
        <el-button type="text" class="nav-btn" @click="handleLogout">
          <i class="el-icon-switch-button"></i> 退出
        </el-button>
      </div>
    </div>

    <!-- 主内容区 -->
    <div class="page-main">
      <div class="page-main-content">
        <!-- 页面头部 -->
        <div class="page-hero">
          <div>
            <h1 class="page-title">我的项目</h1>
            <p class="page-subtitle">管理您的所有短剧创作项目</p>
          </div>
          <el-button type="primary" size="large" icon="el-icon-plus" @click="showCreateDialog = true">
            创建新项目
          </el-button>
        </div>

        <!-- API 警告 -->
        <el-alert 
          v-if="!hasApiKey" 
          type="warning" 
          :closable="false" 
          class="api-warning"
          show-icon
        >
          <template slot="title">
            <strong>提示：</strong> 请先配置 API 密钥才能使用 AI 功能
          </template>
          <el-button size="small" type="text" @click="showConfigDialog = true">
            立即配置 →
          </el-button>
        </el-alert>

        <!-- 项目卡片网格 -->
        <div v-loading="loading" class="projects-grid">
          <!-- 现有项目卡片 -->
          <div 
            v-for="project in projects" 
            :key="project.id" 
            class="project-card"
            @click="gotoWorkbench(project.id)"
          >
            <div class="project-card-header" :style="{background: getProjectGradient(project)}">
              <div class="project-badge">{{ project.genre || '项目' }}</div>
              <div class="project-actions-menu">
                <el-dropdown trigger="click" @command="handleCommand($event, project)" @click.native.stop>
                  <span class="dropdown-trigger">
                    <i class="el-icon-more"></i>
                  </span>
                  <el-dropdown-menu slot="dropdown">
                    <el-dropdown-item command="delete">
                      <i class="el-icon-delete"></i> 删除项目
                    </el-dropdown-item>
                  </el-dropdown-menu>
                </el-dropdown>
              </div>
            </div>
            
            <div class="project-card-body">
              <h3 class="project-name">{{ project.name }}</h3>
              
              <div class="project-stats">
                <div class="stat-item">
                  <i class="el-icon-document"></i>
                  <span>{{ project.novel_content ? project.novel_content.length : 0 }} 字</span>
                </div>
                <div class="stat-item">
                  <i class="el-icon-time"></i>
                  <span>{{ formatDate(project.create_time) }}</span>
                </div>
              </div>

              <div class="project-actions">
                <el-button class="action-btn" @click.stop="gotoNovel(project.id)">
                  <i class="el-icon-edit"></i>
                  <span>编辑小说</span>
                </el-button>
                <el-button class="action-btn" @click.stop="gotoAssets(project.id)">
                  <i class="el-icon-files"></i>
                  <span>资产管理</span>
                </el-button>
                <el-button class="action-btn" @click.stop="gotoCharacters(project.id)">
                  <i class="el-icon-user"></i>
                  <span>角色</span>
                </el-button>
                <el-button class="action-btn" @click.stop="gotoShots(project.id)">
                  <i class="el-icon-film"></i>
                  <span>分镜</span>
                </el-button>
              </div>
            </div>
          </div>

          <!-- 创建新项目卡片 -->
          <div class="project-card project-card-create" @click="showCreateDialog = true">
            <div class="create-content">
              <div class="create-icon">
                <i class="el-icon-plus"></i>
              </div>
              <h3 class="create-title">创建新项目</h3>
              <p class="create-desc">开始您的短剧创作之旅</p>
            </div>
          </div>

          <!-- 空状态 -->
          <div v-if="!loading && projects.length === 0" class="empty-state">
            <div class="empty-icon">
              <i class="el-icon-folder-opened"></i>
            </div>
            <h3 class="empty-title">还没有项目</h3>
            <p class="empty-desc">点击上方按钮创建您的第一个短剧项目</p>
          </div>
        </div>
      </div>
    </div>
    
    <!-- 新建项目对话框 -->
    <el-dialog title="新建项目" :visible.sync="showCreateDialog" width="500px">
      <el-form :model="createForm" :rules="createRules" ref="createForm" label-width="100px">
        <el-form-item label="项目名称" prop="name">
          <el-input v-model="createForm.name" placeholder="请输入项目名称"></el-input>
        </el-form-item>
      </el-form>
      <span slot="footer">
        <el-button @click="showCreateDialog = false">取消</el-button>
        <el-button type="primary" @click="handleCreate">创建</el-button>
      </span>
    </el-dialog>
    
    <!-- 配置API密钥对话框 -->
    <el-dialog title="配置API密钥" :visible.sync="showConfigDialog" width="600px">
      <el-form :model="configForm" label-width="120px">
        <el-form-item label="API密钥">
          <el-input v-model="configForm.doubao_api_key" placeholder="请输入智谱API密钥" type="password" show-password></el-input>
        </el-form-item>
        <el-form-item label="API地址">
          <el-input v-model="configForm.doubao_base_url" placeholder="https://open.bigmodel.cn/api/paas/v4"></el-input>
        </el-form-item>
        <el-form-item label="模型">
          <el-input v-model="configForm.doubao_model" placeholder="glm-4.7-flash"></el-input>
        </el-form-item>
        <el-alert type="info" :closable="false">
          <p>默认使用智谱免费模型 glm-4.7-flash（免费，无token上限）。API密钥仅保存在您的账号下，不会泄露给其他用户。</p>
        </el-alert>
      </el-form>
      <span slot="footer">
        <el-button @click="showConfigDialog = false">取消</el-button>
        <el-button type="primary" @click="handleSaveConfig">保存</el-button>
      </span>
    </el-dialog>
  </div>
</template>

<script>
import { api } from '@/api'

export default {
  name: 'ProjectList',
  data() {
    return {
      loading: false,
      projects: [],
      hasApiKey: false,
      showCreateDialog: false,
      showConfigDialog: false,
      createForm: {
        name: ''
      },
      createRules: {
        name: [{ required: true, message: '请输入项目名称', trigger: 'blur' }]
      },
      configForm: {
        doubao_api_key: '',
        doubao_base_url: 'https://open.bigmodel.cn/api/paas/v4',
        doubao_model: 'glm-4.7-flash'
      }
    }
  },
  async mounted() {
    await this.loadProjects()
    await this.loadConfig()
  },
  methods: {
    async loadProjects() {
      this.loading = true
      try {
        this.projects = await api.project.list()
      } catch (error) {
        console.error('加载项目失败:', error)
        this.$message.error('加载项目失败')
      } finally {
        this.loading = false
      }
    },

    getProjectGradient(project) {
      const gradients = [
        'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
        'linear-gradient(135deg, #f093fb 0%, #f5576c 100%)',
        'linear-gradient(135deg, #4facfe 0%, #00f2fe 100%)',
        'linear-gradient(135deg, #43e97b 0%, #38f9d7 100%)',
        'linear-gradient(135deg, #fa709a 0%, #fee140 100%)',
        'linear-gradient(135deg, #30cfd0 0%, #330867 100%)'
      ]
      const index = Math.abs((project.id || '').charCodeAt(0) || 0) % gradients.length
      return gradients[index]
    },

    handleCommand(command, project) {
      if (command === 'delete') {
        this.handleDelete(project)
      }
    },
    
    async loadConfig() {
      try {
        const res = await api.auth.getConfig()
        this.hasApiKey = res.data.has_api_key
        this.configForm.doubao_base_url = res.data.doubao_base_url
        this.configForm.doubao_model = res.data.doubao_model
        this.$store.dispatch('setHasApiKey', res.data.has_api_key)
      } catch (error) {
        console.error('加载配置失败:', error)
      }
    },
    
    handleCreate() {
      this.$refs.createForm.validate(async valid => {
        if (!valid) return
        
        try {
          await api.project.create(this.createForm)
          this.$message.success('项目创建成功')
          this.showCreateDialog = false
          this.createForm.name = ''
          await this.loadProjects()
        } catch (error) {
          console.error('创建项目失败:', error)
        }
      })
    },
    
    async handleSaveConfig() {
      try {
        await api.auth.updateConfig(this.configForm)
        this.$message.success('配置保存成功')
        this.showConfigDialog = false
        await this.loadConfig()
      } catch (error) {
        console.error('保存配置失败:', error)
      }
    },
    
    handleDelete(project) {
      this.$confirm(`确定要删除项目"${project.name}"吗？删除后无法恢复。`, '提示', {
        confirmButtonText: '确定',
        cancelButtonText: '取消',
        type: 'warning'
      }).then(async () => {
        try {
          await api.project.delete(project.id)
          this.$message.success('删除成功')
          await this.loadProjects()
        } catch (error) {
          console.error('删除项目失败:', error)
        }
      }).catch(() => {})
    },
    
    gotoWorkbench(projectId) {
      this.$router.push(`/projects/${projectId}`)
    },

    gotoNovel(projectId) {
      this.$router.push({ path: `/projects/${projectId}`, query: { tab: 'novel' } })
    },

    gotoAssets(projectId) {
      this.$router.push({ path: `/projects/${projectId}`, query: { tab: 'asset' } })
    },
    gotoCharacters(projectId) {
      this.$router.push({ path: `/projects/${projectId}`, query: { tab: 'character' } })
    },

    gotoShots(projectId) {
      this.$router.push({ path: `/projects/${projectId}`, query: { tab: 'shot' } })
    },
    
    handleLogout() {
      this.$store.dispatch('logout')
      this.$router.push('/login')
    },
    
    formatDate(dateStr) {
      if (!dateStr) return '刚刚'
      const date = new Date(dateStr)
      const now = new Date()
      const diff = now - date
      const minutes = Math.floor(diff / 60000)
      const hours = Math.floor(diff / 3600000)
      const days = Math.floor(diff / 86400000)
      
      if (minutes < 1) return '刚刚'
      if (minutes < 60) return `${minutes}分钟前`
      if (hours < 24) return `${hours}小时前`
      if (days < 7) return `${days}天前`
      return date.toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' })
    }
  }
}
</script>

<style scoped>
.project-list-container {
  min-height: 100vh;
  background: var(--bg-dark-primary);
  position: relative;
}

/* 科技感背景 */
.project-list-container::before {
  content: '';
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: 
    radial-gradient(circle at 20% 50%, rgba(102, 126, 234, 0.15) 0%, transparent 50%),
    radial-gradient(circle at 80% 80%, rgba(118, 75, 162, 0.15) 0%, transparent 50%);
  pointer-events: none;
  z-index: 0;
}

/* 顶部导航栏 */
.top-bar {
  background: rgba(30, 41, 59, 0.8);
  backdrop-filter: blur(20px);
  box-shadow: 0 4px 24px rgba(0, 0, 0, 0.4);
  border-bottom: 1px solid rgba(255, 255, 255, 0.1);
  padding: 16px 48px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  position: sticky;
  top: 0;
  z-index: 100;
}

.logo-section {
  display: flex;
  align-items: center;
  gap: 16px;
}

.logo {
  font-size: 24px;
  font-weight: 700;
  background: var(--primary-gradient);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
  cursor: pointer;
  transition: var(--transition);
}

.logo:hover {
  opacity: 0.8;
}

.tagline {
  font-size: 13px;
  color: var(--text-tertiary);
}

.nav-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.nav-btn {
  color: var(--text-light);
  font-weight: 500;
  transition: var(--transition);
  padding: 8px 16px;
}

.nav-btn:hover {
  color: var(--primary-light);
  background: rgba(102, 126, 234, 0.1);
}

/* 主内容区 */
.page-main {
  padding: 48px;
  position: relative;
  z-index: 1;
}

.page-main-content {
  max-width: 1400px;
  margin: 0 auto;
}

/* 页面头部 */
.page-hero {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 32px;
}

.page-title {
  font-size: 32px;
  font-weight: 700;
  color: var(--text-light);
  margin: 0 0 8px 0;
}

.page-subtitle {
  font-size: 15px;
  color: var(--text-tertiary);
  margin: 0;
}

/* API 警告 */
.api-warning {
  margin-bottom: 32px;
  border-radius: var(--radius-md);
  padding: 16px 20px;
  background: rgba(245, 158, 11, 0.1);
  border: 1px solid rgba(245, 158, 11, 0.3);
}

.api-warning >>> .el-alert__title {
  color: var(--warning);
}

.api-warning >>> .el-button--text {
  color: var(--warning);
  font-weight: 600;
  padding: 0;
}

/* 项目网格 */
.projects-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 24px;
  min-height: 300px;
}

/* 项目卡片 - 暗色科技风 */
.project-card {
  background: rgba(30, 41, 59, 0.6);
  backdrop-filter: blur(20px);
  border-radius: var(--radius-lg);
  overflow: hidden;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4);
  border: 1px solid rgba(255, 255, 255, 0.1);
  transition: var(--transition);
  display: flex;
  flex-direction: column;
  position: relative;
}

.project-card::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: linear-gradient(135deg, rgba(102, 126, 234, 0.05) 0%, transparent 50%);
  opacity: 0;
  transition: var(--transition);
  pointer-events: none;
}

.project-card:hover {
  transform: translateY(-4px);
  box-shadow: 0 16px 48px rgba(0, 0, 0, 0.6);
  border-color: rgba(102, 126, 234, 0.4);
}

.project-card:hover::before {
  opacity: 1;
}

.project-card-header {
  height: 120px;
  position: relative;
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  padding: 16px;
}

.project-badge {
  background: rgba(255, 255, 255, 0.15);
  backdrop-filter: blur(10px);
  color: white;
  padding: 6px 14px;
  border-radius: var(--radius-full);
  font-size: 12px;
  font-weight: 600;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
  border: 1px solid rgba(255, 255, 255, 0.2);
}

.project-actions-menu {
  background: rgba(255, 255, 255, 0.1);
  backdrop-filter: blur(10px);
  width: 32px;
  height: 32px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: var(--transition);
  border: 1px solid rgba(255, 255, 255, 0.2);
}

.project-actions-menu:hover {
  background: rgba(255, 255, 255, 0.2);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
}

.dropdown-trigger {
  color: white;
  font-size: 18px;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  height: 100%;
}

.project-card-body {
  padding: 24px;
  flex: 1;
  display: flex;
  flex-direction: column;
  background: rgba(15, 23, 42, 0.5);
}

.project-name {
  font-size: 18px;
  font-weight: 600;
  color: var(--text-light);
  margin: 0 0 16px 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.project-stats {
  display: flex;
  gap: 20px;
  margin-bottom: 20px;
  padding-bottom: 16px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.1);
}

.stat-item {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--text-tertiary);
  font-size: 13px;
}

.stat-item i {
  font-size: 16px;
  color: var(--primary-light);
}

.project-actions {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 8px;
  margin-top: auto;
}

.action-btn {
  padding: 10px 12px;
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: var(--radius);
  background: rgba(15, 23, 42, 0.5);
  color: var(--text-light);
  transition: var(--transition);
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
}

.action-btn:hover {
  background: var(--primary-gradient);
  color: white;
  border-color: transparent;
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(102, 126, 234, 0.4);
}

.action-btn i {
  font-size: 14px;
}

/* 创建项目卡片 */
.project-card-create {
  border: 2px dashed rgba(255, 255, 255, 0.2);
  background: rgba(30, 41, 59, 0.3);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 360px;
  position: relative;
  overflow: hidden;
}

.project-card-create::before {
  content: '';
  position: absolute;
  inset: 0;
  background: radial-gradient(circle at center, rgba(102, 126, 234, 0.1) 0%, transparent 70%);
  opacity: 0;
  transition: var(--transition);
}

.project-card-create:hover {
  border-color: var(--primary);
  background: rgba(102, 126, 234, 0.05);
}

.project-card-create:hover::before {
  opacity: 1;
}

.create-content {
  text-align: center;
  padding: 32px;
  position: relative;
  z-index: 1;
}

.create-icon {
  width: 80px;
  height: 80px;
  margin: 0 auto 20px;
  border-radius: 50%;
  background: linear-gradient(135deg, rgba(102, 126, 234, 0.2) 0%, rgba(118, 75, 162, 0.2) 100%);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 36px;
  color: var(--primary-light);
  transition: var(--transition);
  border: 2px solid rgba(102, 126, 234, 0.3);
}

.project-card-create:hover .create-icon {
  background: linear-gradient(135deg, rgba(102, 126, 234, 0.3) 0%, rgba(118, 75, 162, 0.3) 100%);
  transform: scale(1.05);
  box-shadow: 0 8px 24px rgba(102, 126, 234, 0.3);
}

.create-title {
  font-size: 18px;
  font-weight: 600;
  color: var(--text-light);
  margin: 0 0 8px 0;
}

.create-desc {
  font-size: 14px;
  color: var(--text-tertiary);
  margin: 0;
}

/* 空状态 */
.empty-state {
  grid-column: 1 / -1;
  text-align: center;
  padding: 80px 20px;
}

.empty-icon {
  font-size: 72px;
  color: rgba(255, 255, 255, 0.2);
  margin-bottom: 20px;
}

.empty-title {
  font-size: 20px;
  font-weight: 600;
  color: var(--text-secondary);
  margin: 0 0 12px 0;
}

.empty-desc {
  font-size: 14px;
  color: var(--text-tertiary);
  margin: 0;
}

/* 对话框样式 - 暗色 */
>>> .el-dialog {
  background: var(--bg-dark-secondary);
  border-radius: var(--radius-md);
  box-shadow: 0 16px 48px rgba(0, 0, 0, 0.8);
  border: 1px solid rgba(255, 255, 255, 0.1);
}

>>> .el-dialog__header {
  padding: 24px 24px 16px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.1);
  background: rgba(255, 255, 255, 0.05);
}

>>> .el-dialog__title {
  font-size: 18px;
  font-weight: 600;
  color: var(--text-light);
}

>>> .el-dialog__body {
  padding: 24px;
}

>>> .el-form-item__label {
  font-weight: 500;
  color: var(--text-light);
}

>>> .el-dropdown-menu {
  background: var(--bg-dark-secondary);
  border-radius: var(--radius);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.6);
  border: 1px solid rgba(255, 255, 255, 0.1);
}

>>> .el-dropdown-menu__item {
  padding: 10px 20px;
  color: var(--text-light);
}

>>> .el-dropdown-menu__item:hover {
  background: rgba(102, 126, 234, 0.2);
  color: var(--primary-light);
}

>>> .el-dropdown-menu__item i {
  margin-right: 8px;
  color: var(--primary-light);
}

/* 响应式 */
@media (max-width: 768px) {
  .top-bar {
    padding: 12px 20px;
  }

  .page-main {
    padding: 24px 20px;
  }

  .page-hero {
    flex-direction: column;
    align-items: flex-start;
    gap: 20px;
  }

  .projects-grid {
    grid-template-columns: 1fr;
  }
}
</style>
