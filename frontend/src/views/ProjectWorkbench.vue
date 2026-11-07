<template>
  <div class="project-workbench-container">
    <!-- 顶部导航 -->
    <div class="workbench-nav">
      <el-button icon="el-icon-back" class="nav-back" @click="$router.push(`/projects/${projectId}`)">返回</el-button>
      <div class="nav-title">{{ project ? project.name : '加载中...' }}</div>
      <div class="nav-right">
        <el-button size="small" type="text" @click="$router.push('/projects')">
          <i class="el-icon-folder-opened"></i> 全部项目
        </el-button>
      </div>
    </div>

    <!-- Tab 导航 -->
    <el-tabs v-model="activeTab" class="workbench-tabs" @tab-click="onTabClick">
      <el-tab-pane label="📖 小说" name="novel"></el-tab-pane>
      <el-tab-pane label="🗂 资产" name="asset"></el-tab-pane>
      <el-tab-pane label="👤 角色" name="character"></el-tab-pane>
      <el-tab-pane label="🎬 分镜" name="shot"></el-tab-pane>
    </el-tabs>

    <!-- 内容区：v-show 保持各面板实例，切换不重载 -->
    <div class="workbench-body">
      <NovelPanel ref="novelPanel" v-show="activeTab === 'novel'" :project-id="projectId" :video-set-id="videoSetId" />
      <AssetPanel ref="assetPanel" v-show="activeTab === 'asset'" :project-id="projectId" />
      <CharacterPanel ref="characterPanel" v-show="activeTab === 'character'" :project-id="projectId" />
      <ShotPanel ref="shotPanel" v-show="activeTab === 'shot'" :project-id="projectId" :video-set-id="videoSetId" />
    </div>
  </div>
</template>

<script>
import { api } from '@/api'
import NovelPanel from './project/NovelPanel.vue'
import AssetPanel from './project/AssetPanel.vue'
import CharacterPanel from './project/CharacterPanel.vue'
import ShotPanel from './project/ShotPanel.vue'

export default {
  name: 'ProjectWorkbench',
  components: { NovelPanel, AssetPanel, CharacterPanel, ShotPanel },
  data() {
    return {
      projectId: '',
      project: null,
      activeTab: 'shot',
      videoSetId: ''
    }
  },
  async mounted() {
    this.projectId = this.$route.params.projectId
    this.videoSetId = this.$route.query.video_set_id || ''
    const tab = this.$route.query.tab
    if (['novel', 'asset', 'character', 'shot'].includes(tab)) {
      this.activeTab = tab
    } else {
      // 默认判断：如果没有分镜，就显示小说页；有分镜就显示分镜页
      try {
        const shots = await api.shot.list(this.projectId, this.videoSetId)
        if (shots && shots.length > 0) {
          this.activeTab = 'shot'
        } else {
          this.activeTab = 'novel'
        }
      } catch (e) {
        this.activeTab = 'novel'
      }
    }
    try {
      this.project = await api.project.get(this.projectId)
    } catch (error) {
      console.error('加载项目失败:', error)
    }
  },
  methods: {
    onTabClick(tab) {
      this.activeTab = tab.name
      // v-show 面板常驻实例、切 tab 不会重新 mounted，这里主动刷新对应面板数据
      const refreshMap = {
        asset: () => this.$refs.assetPanel && this.$refs.assetPanel.loadAll(),
        character: () => this.$refs.characterPanel && this.$refs.characterPanel.loadCharacters(),
        shot: () => this.$refs.shotPanel && this.$refs.shotPanel.loadShots()
      }
      const refresh = refreshMap[tab.name]
      if (refresh) refresh()
    }
  }
}
</script>

<style scoped>
.project-workbench-container {
  min-height: 100vh;
  background: var(--bg-dark-primary);
  position: relative;
}


.project-workbench-container::before {
  content: '';
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background:
    radial-gradient(circle at 20% 50%, rgba(102, 126, 234, 0.1) 0%, transparent 50%),
    radial-gradient(circle at 80% 80%, rgba(118, 75, 162, 0.1) 0%, transparent 50%);
  pointer-events: none;
  z-index: 0;
}

/* 顶部导航 */
.workbench-nav {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 28px;
  background: rgba(30, 41, 59, 0.8);
  backdrop-filter: blur(20px);
  box-shadow: 0 4px 24px rgba(0, 0, 0, 0.4);
  border-bottom: 1px solid rgba(255, 255, 255, 0.1);
  position: sticky;
  top: 0;
  z-index: 100;
}

.nav-back {
  min-width: 96px;
  background: rgba(255,255,255,0.08);
  border-color: rgba(255,255,255,0.15);
  color: #ddd;
}

.nav-title {
  font-size: 20px;
  font-weight: 700;
  color: var(--text-light);
  background: var(--primary-gradient);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
  flex: 1;
  text-align: center;
  padding: 0 20px;
}

.nav-right {
  min-width: 96px;
  text-align: right;
}

/* Tab 导航栏 */
.workbench-tabs {
  background: rgba(15, 23, 42, 0.6);
  backdrop-filter: blur(20px);
  padding: 0 28px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  position: sticky;
  top: 56px;
  z-index: 90;
}

.workbench-tabs >>> .el-tabs__nav-wrap::after {
  background-color: rgba(255, 255, 255, 0.1);
}

.workbench-tabs >>> .el-tabs__active-bar {
  background: var(--primary-gradient);
  height: 3px;
}

.workbench-tabs >>> .el-tabs__item {
  color: var(--text-tertiary);
  font-weight: 500;
  font-size: 15px;
  height: 48px;
  line-height: 48px;
  transition: color 0.2s;
}

.workbench-tabs >>> .el-tabs__item:hover {
  color: var(--text-light);
}

.workbench-tabs >>> .el-tabs__item.is-active {
  color: var(--text-light);
  font-weight: 600;
}

/* 隐藏 el-tabs 自带空内容区，内容由下方 workbench-body 控制 */
.workbench-tabs >>> .el-tabs__content {
  display: none;
}

/* 内容区 */
.workbench-body {
  padding: 28px;
  position: relative;
  z-index: 1;
  max-width: 1680px;
  margin: 0 auto;
}
</style>
