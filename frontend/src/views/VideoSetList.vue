<template>
  <div class="video-set-list">
    <div class="header">
      <el-button icon="el-icon-back" @click="$router.push('/projects')" size="small"
        style="background:rgba(255,255,255,0.08);border-color:rgba(255,255,255,0.15);color:#ddd">项目列表</el-button>
      <h2>{{ project ? project.name : '加载中...' }}</h2>
      <el-button type="primary" icon="el-icon-plus" size="small" @click="addSet">新建视频</el-button>
    </div>

    <div class="set-grid" v-loading="loading">
      <div class="set-card" v-for="s in sets" :key="s.id" @click="enterSet(s)">
        <div class="set-cover" v-if="s.cover_url">
          <img :src="s.cover_url" />
        </div>
        <div class="set-cover placeholder" v-else>
          <i class="el-icon-picture-outline"></i>
        </div>
        <div class="set-name">{{ s.name }}</div>
        <div class="set-stats">
          <span>{{ s.shot_count }} 个镜头</span>
          <span>{{ s.video_count }} 个视频</span>
        </div>
        <div class="set-actions" @click.stop>
          <el-button size="mini" type="text" icon="el-icon-download" @click="exportToJianying(s)">导出剪映</el-button>
          <el-button size="mini" type="text" icon="el-icon-picture" @click="genCover(s)">生成封面</el-button>
          <el-button size="mini" type="text" icon="el-icon-edit" @click="renameSet(s)">重命名</el-button>
          <el-button size="mini" type="text" icon="el-icon-delete" style="color:#f56c6c" @click="deleteSet(s)">删除</el-button>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import { api } from '@/api'

export default {
  data() {
    return {
      projectId: '',
      project: null,
      sets: [],
      loading: false
    }
  },
  async mounted() {
    this.projectId = this.$route.params.projectId
    await this.loadProject()
    await this.loadSets()
  },
  methods: {
    async loadProject() {
      try {
        this.project = await api.project.get(this.projectId)
      } catch (e) {}
    },
    async loadSets() {
      this.loading = true
      try {
        const token = localStorage.getItem('token')
        const res = await fetch(`/api/video-set/list?project_id=${this.projectId}`, {
          headers: { 'Authorization': 'Bearer ' + token }
        })
        this.sets = await res.json()
      } catch (e) {
        console.error(e)
      } finally {
        this.loading = false
      }
    },
    enterSet(s) {
      this.$router.push(`/projects/${this.projectId}/workbench?video_set_id=${s.id}`)
    },
    async exportToJianying(s) {
      try {
        const token = localStorage.getItem('token')
        const res = await fetch(`/api/video/export/jianying?project_id=${this.projectId}&video_set_id=${s.id}`, {
          headers: { 'Authorization': 'Bearer ' + token }
        })
        const data = await res.json()
        if (data.ok) {
          this.$message.success(data.msg || '已导出到剪映')
        } else {
          this.$message.error(data.msg || '导出失败')
        }
      } catch (e) {
        this.$message.error('导出失败: ' + e.message)
      }
    },
    async genCover(s) {
      this.$message.info('封面图生成功能开发中')
    },
    goCommon(tab) {
      this.$router.push(`/projects/${this.projectId}/workbench?tab=${tab}`)
    },
    async addSet() {
      try {
        const { value: name } = await this.$prompt('输入视频名称', '新建视频')
        if (!name) return
        const token = localStorage.getItem('token')
        await fetch(`/api/video-set/create`, {
          method: 'POST',
          headers: { 'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json' },
          body: JSON.stringify({ project_id: this.projectId, name })
        })
        await this.loadSets()
      } catch (e) {}
    },
    async renameSet(s) {
      try {
        const { value: name } = await this.$prompt('新名称', '重命名', { defaultValue: s.name })
        if (!name) return
        const token = localStorage.getItem('token')
        await fetch(`/api/video-set/rename?set_id=${s.id}`, {
          method: 'POST',
          headers: { 'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json' },
          body: JSON.stringify({ name })
        })
        await this.loadSets()
      } catch (e) {}
    },
    async deleteSet(s) {
      try {
        await this.$confirm(`确定删除"${s.name}"及其所有分镜？`, '确认', { type: 'warning' })
        const token = localStorage.getItem('token')
        await fetch(`/api/video-set/delete?set_id=${s.id}`, {
          method: 'DELETE',
          headers: { 'Authorization': 'Bearer ' + token }
        })
        await this.loadSets()
      } catch (e) {}
    }
  }
}
</script>

<style scoped>
.video-set-list {
  min-height: 100vh;
  background: var(--bg-dark-primary);
  padding: 24px;
}
.header {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 32px;
}
.header h2 {
  flex: 1;
  color: var(--text-light);
  margin: 0;
}
.header-actions {
  display: flex;
  gap: 8px;
}
.set-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 20px;
}
.set-card {
  background: rgba(30, 41, 59, 0.8);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 12px;
  padding: 0;
  cursor: pointer;
  transition: all 0.2s;
  overflow: hidden;
}
.set-card:hover {
  border-color: var(--primary-color);
  transform: translateY(-2px);
}
.set-cover {
  width: 100%;
  height: 160px;
  overflow: hidden;
  background: rgba(0,0,0,0.2);
}
.set-cover img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}
.set-cover.placeholder {
  display: flex;
  align-items: center;
  justify-content: center;
  color: rgba(255,255,255,0.2);
  font-size: 40px;
}
.set-name {
  font-size: 18px;
  font-weight: 600;
  color: var(--text-light);
  margin: 16px 16px 8px;
}
.set-stats {
  display: flex;
  gap: 16px;
  color: var(--text-tertiary);
  font-size: 13px;
  margin: 0 16px 12px;
}
.set-actions {
  display: flex;
  gap: 4px;
  padding: 0 12px 12px;
  flex-wrap: wrap;
}
</style>
