<template>
  <div class="dashboard-container">
    <!-- 顶部导航栏 -->
    <div class="top-bar">
      <div class="logo-section">
        <div class="logo">🎬 DongAI</div>
        <div class="tagline">AI短剧创作平台</div>
      </div>
      <div class="nav-actions">
        <el-tooltip content="提示词管理" placement="bottom">
          <el-button icon="el-icon-magic-stick" circle @click="$router.push('/prompts')"
            style="background:rgba(255,255,255,0.08);border-color:rgba(255,255,255,0.15);color:#ddd"></el-button>
        </el-tooltip>
        <el-tooltip content="账号管理" placement="bottom">
          <el-button icon="el-icon-user" circle @click="$router.push('/accounts')"
            style="background:rgba(255,255,255,0.08);border-color:rgba(255,255,255,0.15);color:#ddd"></el-button>
        </el-tooltip>
        <el-tooltip content="模型管理" placement="bottom">
          <el-button icon="el-icon-cpu" circle @click="$router.push('/models')"
            style="background:rgba(255,255,255,0.08);border-color:rgba(255,255,255,0.15);color:#ddd"></el-button>
        </el-tooltip>
        <el-button icon="el-icon-search" circle
          style="background:rgba(255,255,255,0.08);border-color:rgba(255,255,255,0.15);color:#ddd"></el-button>
        <el-button icon="el-icon-bell" circle
          style="background:rgba(255,255,255,0.08);border-color:rgba(255,255,255,0.15);color:#ddd"></el-button>
        <el-avatar :size="40" src="https://cube.elemecdn.com/0/88/03b0d39583f48206768a7534e55bcpng.png"></el-avatar>
      </div>
    </div>

    <!-- Hero 区域 -->
    <div class="hero-section fade-in">
      <div class="hero-content">
        <div class="hero-badge">✨ 新功能上线</div>
        <h1 class="hero-title">
          用AI创作<br/>
          <span class="gradient-text">属于你的短剧</span>
        </h1>
        <p class="hero-description">
          从剧本到成片，一站式AI短剧创作平台<br/>
          让创意无限，让创作更简单
        </p>
        <div class="hero-actions">
          <el-button type="primary" size="large" @click="createProject" class="btn-hero">
            <i class="el-icon-plus"></i> 创建新项目
          </el-button>
          <el-button size="large" class="btn-outline">
            <i class="el-icon-video-play"></i> 观看教程
          </el-button>
        </div>
      </div>
      <div class="hero-illustration">
        <div class="floating-card card-1">
          <i class="el-icon-film"></i>
          <div>12个分镜</div>
        </div>
        <div class="floating-card card-2">
          <i class="el-icon-user"></i>
          <div>8个角色</div>
        </div>
        <div class="floating-card card-3">
          <i class="el-icon-picture"></i>
          <div>生成中...</div>
        </div>
      </div>
    </div>

    <!-- 统计数据区域 -->
    <div class="metrics-section fade-in" style="animation-delay: 0.1s">
      <div class="section-header">
        <h2 class="section-title">数据概览</h2>
        <el-button type="text">查看详细 →</el-button>
      </div>
      <div class="metrics-grid">
        <div class="metric-card" v-for="(metric, index) in metrics" :key="index">
          <div class="metric-icon" :class="metric.iconClass">
            <i :class="metric.icon"></i>
          </div>
          <div class="metric-body">
            <div class="metric-value">{{ metric.value }}</div>
            <div class="metric-label">{{ metric.label }}</div>
            <div class="metric-change" :class="metric.change > 0 ? 'positive' : 'negative'">
              <i :class="metric.change > 0 ? 'el-icon-top' : 'el-icon-bottom'"></i>
              {{ Math.abs(metric.change) }}% vs 上周
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 项目展示区域 -->
    <div class="projects-section fade-in" style="animation-delay: 0.2s">
      <div class="section-header">
        <h2 class="section-title">最近项目</h2>
        <div class="header-actions">
          <el-button type="text" @click="$router.push('/projects')">查看全部</el-button>
        </div>
      </div>
      <div class="projects-masonry">
        <div class="project-item" v-for="project in recentProjects" :key="project.id" @click="openProject(project)">
          <div class="project-thumbnail" :style="{background: getProjectGradient(project)}">
            <div class="project-status" :class="project.status">{{ project.statusText }}</div>
            <div class="project-overlay">
              <i class="el-icon-video-play"></i>
            </div>
          </div>
          <div class="project-details">
            <h3 class="project-name">{{ project.name }}</h3>
            <div class="project-stats">
              <span><i class="el-icon-film"></i> {{ project.shot_count || 0 }}</span>
              <span><i class="el-icon-time"></i> {{ formatTime(project.updated_at) }}</span>
            </div>
            <div class="project-progress-bar">
              <div class="progress-fill" :style="{width: project.progress + '%', background: getProjectGradient(project)}"></div>
              <span class="progress-label">{{ project.progress }}%</span>
            </div>
            <div class="project-tags">
              <span class="tag">{{ project.genre || '玄幻' }}</span>
            </div>
          </div>
        </div>
        
        <!-- 创建项目卡片 -->
        <div class="project-item project-create" @click="createProject">
          <div class="create-content">
            <div class="create-icon">
              <i class="el-icon-plus"></i>
            </div>
            <div class="create-text">创建新项目</div>
          </div>
        </div>
      </div>
    </div>

    <!-- 创建项目对话框 -->
    <el-dialog title="创建新项目" :visible.sync="showCreateDialog" width="500px">
      <el-form :model="newProject" label-width="80px">
        <el-form-item label="项目名称">
          <el-input v-model="newProject.name" placeholder="请输入项目名称"></el-input>
        </el-form-item>
        <el-form-item label="项目类型">
          <el-select v-model="newProject.genre" placeholder="选择类型" style="width: 100%">
            <el-option label="玄幻" value="玄幻"></el-option>
            <el-option label="都市" value="都市"></el-option>
            <el-option label="仙侠" value="仙侠"></el-option>
            <el-option label="末世" value="末世"></el-option>
            <el-option label="古风" value="古风"></el-option>
          </el-select>
        </el-form-item>
      </el-form>
      <span slot="footer">
        <el-button @click="showCreateDialog = false">取消</el-button>
        <el-button type="primary" @click="handleCreate">创建</el-button>
      </span>
    </el-dialog>
  </div>
</template>

<script>
import { api } from '@/api'

export default {
  name: 'Dashboard',
  data() {
    return {
      metrics: [
        { icon: 'el-icon-folder-opened', label: '总项目数', value: 0, iconClass: 'icon-purple', change: 12 },
        { icon: 'el-icon-film', label: '分镜总数', value: 0, iconClass: 'icon-blue', change: 8 },
        { icon: 'el-icon-video-camera', label: '已生成视频', value: 0, iconClass: 'icon-green', change: 15 },
        { icon: 'el-icon-time', label: '总时长', value: '0min', iconClass: 'icon-orange', change: 5 }
      ],
      recentProjects: [],
      showCreateDialog: false,
      newProject: {
        name: '',
        genre: '玄幻'
      }
    }
  },
  async mounted() {
    await this.loadStats()
    await this.loadRecentProjects()
  },
  methods: {
    async loadStats() {
      try {
        const projects = await api.project.list()
        this.metrics[0].value = projects.length
        
        let totalShots = 0
        for (const project of projects.slice(0, 10)) {
          const shots = await api.shot.list(project.id)
          totalShots += shots.length
        }
        this.metrics[1].value = totalShots
      } catch (error) {
        console.error('加载统计失败:', error)
      }
    },
    async loadRecentProjects() {
      try {
        const projects = await api.project.list()
        const statuses = ['进行中', '已完成', '草稿']
        this.recentProjects = projects.slice(0, 5).map(p => ({
          ...p,
          progress: Math.floor(Math.random() * 100),
          shot_count: Math.floor(Math.random() * 20),
          status: statuses[Math.floor(Math.random() * statuses.length)],
          statusText: statuses[Math.floor(Math.random() * statuses.length)]
        }))
      } catch (error) {
        console.error('加载项目失败:', error)
      }
    },
    createProject() {
      this.showCreateDialog = true
    },
    async handleCreate() {
      if (!this.newProject.name) {
        this.$message.warning('请输入项目名称')
        return
      }
      
      try {
        const project = await api.project.create(this.newProject)
        this.$message.success('项目创建成功')
        this.showCreateDialog = false
        this.$router.push(`/projects/${project.id}/novel`)
      } catch (error) {
        console.error('创建项目失败:', error)
      }
    },
    handleAction(actionId) {
      this.createProject()
    },
    openProject(project) {
      this.$router.push(`/projects/${project.id}/assets`)
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
      const index = Math.abs(project.id?.charCodeAt(0) || 0) % gradients.length
      return gradients[index]
    },
    formatTime(time) {
      if (!time) return '刚刚'
      const date = new Date(time)
      const now = new Date()
      const diff = now - date
      const minutes = Math.floor(diff / 60000)
      const hours = Math.floor(diff / 3600000)
      const days = Math.floor(diff / 86400000)
      
      if (minutes < 1) return '刚刚'
      if (minutes < 60) return `${minutes}分钟前`
      if (hours < 24) return `${hours}小时前`
      if (days < 7) return `${days}天前`
      return date.toLocaleDateString()
    }
  }
}
</script>

<style scoped>
.dashboard-container {
  min-height: 100vh;
  background: #0f172a;
  padding: 0;
}

/* 顶部导航栏 */
.top-bar {
  background: rgba(15, 23, 42, 0.8);
  backdrop-filter: blur(12px);
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
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}

.tagline {
  font-size: 13px;
  color: #64748b;
}

.nav-actions {
  display: flex;
  align-items: center;
  gap: 12px;
}

/* Hero 区域 */
.hero-section {
  padding: 80px 48px;
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 80px;
  align-items: center;
  position: relative;
  overflow: hidden;
}

.hero-section::before {
  content: '';
  position: absolute;
  top: -50%;
  right: -20%;
  width: 800px;
  height: 800px;
  background: radial-gradient(circle, rgba(102, 126, 234, 0.15) 0%, transparent 70%);
  border-radius: 50%;
}

.hero-badge {
  display: inline-block;
  padding: 6px 16px;
  background: rgba(99, 102, 241, 0.1);
  border: 1px solid rgba(99, 102, 241, 0.3);
  border-radius: 20px;
  color: #818cf8;
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 24px;
}

.hero-title {
  font-size: 64px;
  font-weight: 800;
  line-height: 1.2;
  color: white;
  margin: 0 0 24px 0;
}

.gradient-text {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}

.hero-description {
  font-size: 18px;
  line-height: 1.8;
  color: #94a3b8;
  margin-bottom: 40px;
}

.hero-actions {
  display: flex;
  gap: 16px;
}

.btn-hero {
  padding: 16px 32px;
  font-size: 16px;
  border-radius: 12px;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  border: none;
  box-shadow: 0 10px 30px rgba(102, 126, 234, 0.3);
}

.btn-outline {
  padding: 16px 32px;
  font-size: 16px;
  border-radius: 12px;
  background: transparent;
  border: 2px solid rgba(255, 255, 255, 0.2);
  color: white;
}

.btn-outline:hover {
  background: rgba(255, 255, 255, 0.05);
  border-color: rgba(255, 255, 255, 0.3);
}

/* Hero 插图 */
.hero-illustration {
  position: relative;
  height: 400px;
}

.floating-card {
  position: absolute;
  padding: 20px 24px;
  background: rgba(255, 255, 255, 0.05);
  backdrop-filter: blur(20px);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 16px;
  color: white;
  font-size: 14px;
  display: flex;
  align-items: center;
  gap: 12px;
  animation: float 3s ease-in-out infinite;
}

.floating-card i {
  font-size: 24px;
}

.card-1 {
  top: 20%;
  left: 10%;
  animation-delay: 0s;
}

.card-2 {
  top: 50%;
  right: 20%;
  animation-delay: 0.5s;
}

.card-3 {
  bottom: 20%;
  left: 30%;
  animation-delay: 1s;
}

@keyframes float {
  0%, 100% { transform: translateY(0); }
  50% { transform: translateY(-20px); }
}

/* 统计数据 */
.metrics-section {
  padding: 0 48px 48px;
}

.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 24px;
}

.section-title {
  font-size: 28px;
  font-weight: 700;
  color: white;
  margin: 0;
}

.metrics-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 24px;
}

.metric-card {
  background: rgba(255, 255, 255, 0.05);
  backdrop-filter: blur(20px);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 20px;
  padding: 28px;
  display: flex;
  gap: 20px;
  transition: all 0.3s ease;
}

.metric-card:hover {
  background: rgba(255, 255, 255, 0.08);
  transform: translateY(-4px);
  box-shadow: 0 20px 40px rgba(0, 0, 0, 0.3);
}

.metric-icon {
  width: 56px;
  height: 56px;
  border-radius: 14px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 24px;
  color: white;
}

.icon-purple { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); }
.icon-blue { background: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%); }
.icon-green { background: linear-gradient(135deg, #43e97b 0%, #38f9d7 100%); }
.icon-orange { background: linear-gradient(135deg, #fa709a 0%, #fee140 100%); }

.metric-body {
  flex: 1;
}

.metric-value {
  font-size: 32px;
  font-weight: 700;
  color: white;
  margin-bottom: 4px;
}

.metric-label {
  font-size: 14px;
  color: #94a3b8;
  margin-bottom: 8px;
}

.metric-change {
  font-size: 13px;
  font-weight: 600;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  border-radius: 8px;
}

.metric-change.positive {
  color: #10b981;
  background: rgba(16, 185, 129, 0.1);
}

.metric-change.negative {
  color: #ef4444;
  background: rgba(239, 68, 68, 0.1);
}

/* 项目展示 */
.projects-section {
  padding: 48px;
}

.projects-masonry {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 24px;
}

.project-item {
  background: rgba(255, 255, 255, 0.05);
  backdrop-filter: blur(20px);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 20px;
  overflow: hidden;
  cursor: pointer;
  transition: all 0.3s ease;
}

.project-item:hover {
  transform: translateY(-8px);
  box-shadow: 0 20px 40px rgba(0, 0, 0, 0.4);
}

.project-thumbnail {
  height: 200px;
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
}

.project-status {
  position: absolute;
  top: 16px;
  right: 16px;
  padding: 6px 12px;
  border-radius: 8px;
  font-size: 12px;
  font-weight: 600;
  background: rgba(255, 255, 255, 0.9);
  color: #1e293b;
}

.project-overlay {
  position: absolute;
  inset: 0;
  background: rgba(0, 0, 0, 0.4);
  display: flex;
  align-items: center;
  justify-content: center;
  opacity: 0;
  transition: opacity 0.3s;
}

.project-item:hover .project-overlay {
  opacity: 1;
}

.project-overlay i {
  font-size: 56px;
  color: white;
}

.project-details {
  padding: 24px;
}

.project-name {
  font-size: 18px;
  font-weight: 600;
  color: white;
  margin: 0 0 12px 0;
}

.project-stats {
  display: flex;
  gap: 16px;
  color: #94a3b8;
  font-size: 13px;
  margin-bottom: 16px;
}

.project-stats span {
  display: flex;
  align-items: center;
  gap: 6px;
}

.project-progress-bar {
  position: relative;
  height: 8px;
  background: rgba(255, 255, 255, 0.1);
  border-radius: 4px;
  overflow: hidden;
  margin-bottom: 12px;
}

.progress-fill {
  height: 100%;
  border-radius: 4px;
  transition: width 0.3s;
}

.progress-label {
  position: absolute;
  right: 0;
  top: -20px;
  font-size: 12px;
  color: #94a3b8;
  font-weight: 600;
}

.project-tags {
  display: flex;
  gap: 8px;
}

.tag {
  padding: 4px 12px;
  background: rgba(99, 102, 241, 0.1);
  border: 1px solid rgba(99, 102, 241, 0.3);
  border-radius: 6px;
  color: #818cf8;
  font-size: 12px;
}

/* 创建项目卡片 */
.project-create {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 360px;
  border: 2px dashed rgba(255, 255, 255, 0.2);
  background: transparent;
}

.project-create:hover {
  border-color: #667eea;
  background: rgba(102, 126, 234, 0.05);
}

.create-content {
  text-align: center;
}

.create-icon {
  width: 80px;
  height: 80px;
  margin: 0 auto 16px;
  border-radius: 50%;
  background: rgba(102, 126, 234, 0.1);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 32px;
  color: #667eea;
}

.create-text {
  font-size: 16px;
  font-weight: 600;
  color: #94a3b8;
}

/* 响应式 */
@media (max-width: 1200px) {
  .hero-section {
    grid-template-columns: 1fr;
  }
  
  .hero-illustration {
    display: none;
  }
  
  .metrics-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}

@media (max-width: 768px) {
  .metrics-grid {
    grid-template-columns: 1fr;
  }
  
  .projects-masonry {
    grid-template-columns: 1fr;
  }
}
</style>
