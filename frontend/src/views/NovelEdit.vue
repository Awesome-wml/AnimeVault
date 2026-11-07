<template>
  <div class="novel-edit-container">
    <el-container>
      <el-header>
        <div class="header-content">
          <el-button icon="el-icon-back" @click="$router.back()"
            style="background:rgba(255,255,255,0.08);border-color:rgba(255,255,255,0.15);color:#ddd">返回</el-button>
          <h3>{{ project ? project.name : '加载中...' }}</h3>
          <div>
            <el-button type="primary" size="small" @click="handleSave" :icon="'el-icon-check'">保存</el-button>
          </div>
        </div>
      </el-header>
      
      <el-main>
        <!-- 小说内容编辑区（主功能） -->
        <el-card class="editor-card" v-loading="generating">
          <div slot="header">
            <span>📖 小说内容</span>
            <span style="float: right; color: #909399; font-size:13px">
              {{ novelContent ? novelContent.length : 0 }} 字
            </span>
          </div>
          
          <el-input
            v-model="novelContent"
            type="textarea"
            :rows="28"
            placeholder="粘贴小说内容到这里，或点击下方「AI生成」自动创作..."
          ></el-input>
        </el-card>

        <!-- AI生成（次要功能，折叠） -->
        <el-collapse v-model="activeCollapse" style="margin-top:16px">
          <el-collapse-item title="✨ AI生成小说（可选）" name="ai">
            <el-form :model="generateForm" label-width="100px">
              <el-form-item label="风格">
                <el-select v-model="generateForm.style" placeholder="选择作品风格" style="width:100%" @change="onStyleSelect">
                  <el-option v-for="s in styleOptions" :key="s.id" :label="s.name + ' - ' + s.desc" :value="s.id"></el-option>
                </el-select>
              </el-form-item>
              
              <el-form-item label="故事梗概">
                <el-input v-model="generateForm.outline" type="textarea" :rows="2" placeholder="简要描述故事情节"></el-input>
              </el-form-item>
              
              <el-form-item label="主角设定">
                <el-input v-model="generateForm.protagonist" type="textarea" :rows="2" placeholder="主角背景、性格等"></el-input>
              </el-form-item>
              
              <el-form-item label="目标字数">
                <el-input-number v-model="generateForm.target_words" :min="1000" :max="50000" :step="1000"></el-input-number>
              </el-form-item>
              
              <el-form-item>
                <el-button type="primary" :loading="generating" @click="handleGenerate">开始生成</el-button>
              </el-form-item>
            </el-form>
          </el-collapse-item>
        </el-collapse>
      </el-main>
    </el-container>
  </div>
</template>

<script>
import { api, STYLE_LIBRARY } from '@/api'

export default {
  name: 'NovelEdit',
  data() {
    return {
      projectId: '',
      project: null,
      generating: false,
      novelContent: '',
      activeCollapse: [],
      generateForm: {
        genre: '玄幻',
        style: 'xuanhuan',
        outline: '',
        protagonist: '',
        target_words: 5000
      },
      styleOptions: STYLE_LIBRARY,
      currentStyle: STYLE_LIBRARY[0]
    }
  },
  async mounted() {
    this.projectId = this.$route.params.projectId
    await this.loadProject()
  },
  methods: {
    onStyleSelect() {
      this.currentStyle = this.styleOptions.find(s => s.id === this.generateForm.style) || null
      if (this.currentStyle) {
        this.generateForm.genre = this.currentStyle.genre
      }
    },

    async loadProject() {
      try {
        this.project = await api.project.get(this.projectId)
        this.novelContent = this.project.novel_content || ''
      } catch (error) {
        console.error('加载项目失败:', error)
        this.$router.back()
      }
    },
    
    async handleGenerate() {
      if (!this.generateForm.outline || !this.generateForm.protagonist) {
        this.$message.warning('请填写故事梗概和主角设定')
        return
      }
      
      this.generating = true
      this.novelContent = ''
      
      const baseURL = process.env.VUE_APP_API_BASE_URL || 'http://localhost:8000'
      const token = localStorage.getItem('token')
      
      const eventSource = new EventSource(
        `${baseURL}/api/novel/generate?${new URLSearchParams({
          project_id: this.projectId,
          genre: this.generateForm.genre,
          style: this.generateForm.style,
          outline: this.generateForm.outline,
          protagonist: this.generateForm.protagonist,
          target_words: this.generateForm.target_words
        })}`,
        {
          headers: {
            'Authorization': `Bearer ${token}`
          }
        }
      )
      
      eventSource.onmessage = (event) => {
        const data = JSON.parse(event.data)
        
        if (data.type === 'chunk') {
          this.novelContent += data.content
        } else if (data.type === 'done') {
          this.$message.success('小说生成完成')
          eventSource.close()
          this.generating = false
        } else if (data.type === 'error') {
          this.$message.error(`生成失败: ${data.message}`)
          eventSource.close()
          this.generating = false
        }
      }
      
      eventSource.onerror = () => {
        this.$message.error('连接失败，请检查网络或API配置')
        eventSource.close()
        this.generating = false
      }
    },
    
    async handleSave() {
      try {
        await api.novel.save(this.projectId, this.novelContent)
        this.$message.success('保存成功')
      } catch (error) {
        console.error('保存失败:', error)
      }
    }
  }
}
</script>

<style scoped>
.novel-edit-container {
  min-height: 100vh;
  background: var(--bg-dark-primary);
  position: relative;
}

.novel-edit-container::before {
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

.el-header {
  background: rgba(30, 41, 59, 0.8);
  backdrop-filter: blur(20px);
  box-shadow: 0 4px 24px rgba(0, 0, 0, 0.4);
  border-bottom: 1px solid rgba(255, 255, 255, 0.1);
  position: sticky;
  top: 0;
  z-index: 100;
}

.header-content {
  display: flex;
  justify-content: space-between;
  align-items: center;
  height: 100%;
  max-width: 1600px;
  margin: 0 auto;
}

.header-content h3 {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
  color: var(--text-light);
  flex: 1;
  text-align: center;
}

.el-main {
  padding: 32px;
  background: transparent;
  position: relative;
  z-index: 1;
  max-width: 1200px;
  margin: 0 auto;
}

.editor-card {
  background: rgba(30, 41, 59, 0.6);
  backdrop-filter: blur(20px);
  border-radius: var(--radius-md);
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4);
  border: 1px solid rgba(255, 255, 255, 0.1);
}

.editor-card >>> .el-card__header {
  background: rgba(255, 255, 255, 0.05);
  border-bottom: 1px solid rgba(255, 255, 255, 0.1);
  font-weight: 600;
  color: var(--text-light);
}

.editor-card >>> .el-card__body {
  padding: 24px;
}

.editor-card >>> .el-textarea__inner {
  font-family: 'PingFang SC', 'Microsoft YaHei', sans-serif;
  font-size: 15px;
  line-height: 1.8;
  border-radius: var(--radius);
  background: rgba(15, 23, 42, 0.5);
  border-color: rgba(255, 255, 255, 0.1);
  color: var(--text-light);
}

>>> .el-collapse {
  background: transparent;
  border: none;
}
>>> .el-collapse-item__header {
  background: rgba(255,255,255,0.05);
  border: 1px solid rgba(255,255,255,0.1);
  border-radius: 8px;
  color: #aaa;
  padding: 0 16px;
}
>>> .el-collapse-item__wrap {
  background: rgba(30,41,59,0.6);
  border: 1px solid rgba(255,255,255,0.1);
  border-top: none;
  border-radius: 0 0 8px 8px;
}
>>> .el-form-item__label {
  font-weight: 500;
  color: var(--text-light);
}
</style>
