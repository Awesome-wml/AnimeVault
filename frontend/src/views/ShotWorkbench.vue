<template>
  <div class="shot-workbench-container">
    <el-container>
      <el-header>
        <div class="header-content">
          <el-button icon="el-icon-back" @click="$router.back()">返回</el-button>
          <h3>{{ project ? project.name : '加载中...' }} - 分镜工作台</h3>
          <div>
            <el-button type="primary" size="small" icon="el-icon-video-camera" @click="showBatchVideoDialog">批量生成视频</el-button>
            <el-button type="success" size="small" @click="handleExportSRT">导出SRT字幕</el-button>
          </div>
        </div>
      </el-header>
      
      <el-main>
        <el-card class="control-card">
          <div slot="header">AI拆分分镜</div>
          <el-form inline>
            <el-form-item>
              <el-input
                v-model="splitText"
                type="textarea"
                :rows="3"
                placeholder="粘贴小说段落，AI将自动拆分成镜头"
                style="width: 600px"
              ></el-input>
            </el-form-item>
            <el-form-item>
              <el-button type="primary" :loading="splitting" @click="handleSplit">拆分分镜</el-button>
            </el-form-item>
          </el-form>
        </el-card>
        
        <el-card>
          <div slot="header" class="card-header">
            <span>分镜列表（{{ shots.length }}个镜头）</span>
          </div>
          
          <el-table :data="shots" v-loading="loading" border>
            <el-table-column prop="shot_no" label="镜号" width="70" align="center"></el-table-column>
            
            <el-table-column label="台词/旁白" min-width="200">
              <template slot-scope="scope">
                <el-input v-model="scope.row.text" size="small" @change="handleUpdate(scope.row)"></el-input>
              </template>
            </el-table-column>
            
            <el-table-column label="提示词" min-width="180">
              <template slot-scope="scope">
                <el-input v-model="scope.row.prompt" size="small" @change="handleUpdate(scope.row)"></el-input>
              </template>
            </el-table-column>
            
            <el-table-column label="负面提示词" min-width="150">
              <template slot-scope="scope">
                <el-input v-model="scope.row.neg_prompt" size="small" @change="handleUpdate(scope.row)"></el-input>
              </template>
            </el-table-column>
            
            <el-table-column label="时长(秒)" width="100">
              <template slot-scope="scope">
                <el-input-number v-model="scope.row.duration" :min="0.5" :max="30" :step="0.5" size="small" @change="handleUpdate(scope.row)"></el-input-number>
              </template>
            </el-table-column>
            
            <el-table-column label="图片" width="150">
              <template slot-scope="scope">
                <div v-if="scope.row.img_path">
                  <el-image
                    :src="getStaticUrl(scope.row.img_path)"
                    :preview-src-list="[getStaticUrl(scope.row.img_path)]"
                    style="width: 60px; height: 60px"
                    fit="cover"
                  ></el-image>
                </div>
                <el-button v-else size="mini" type="primary" :loading="scope.row.generating" @click="handleGenerateImage(scope.row)">生成</el-button>
              </template>
            </el-table-column>
            
            <el-table-column label="音频" width="150">
              <template slot-scope="scope">
                <div v-if="scope.row.audio_path">
                  <audio :src="getStaticUrl(scope.row.audio_path)" controls style="width: 100px; height: 30px"></audio>
                </div>
                <el-button v-else size="mini" type="success" :loading="scope.row.generatingAudio" @click="handleGenerateTTS(scope.row)">配音</el-button>
              </template>
            </el-table-column>
            
            <el-table-column label="操作" width="180" fixed="right">
              <template slot-scope="scope">
                <el-button type="text" size="small" @click="handleRegenerateVideo(scope.row)">重新生成</el-button>
                <el-button type="text" size="small" @click="handleDeleteShot(scope.row)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-main>
    </el-container>
    
    <!-- 批量生成视频对话框 -->
    <el-dialog title="批量生成视频（豆包自动化）" :visible.sync="showBatchVideo" width="600px">
      <div v-if="accountStatus">
        <el-alert type="info" :closable="false" style="margin-bottom: 20px">
          <div>今日可用配额：<strong>{{ accountStatus.total_available_quota }}</strong> 条</div>
          <div>选中分镜数：<strong>{{ shots.length }}</strong> 条</div>
        </el-alert>
        
        <el-table :data="accountStatus.accounts" size="small" border style="margin-bottom: 20px">
          <el-table-column prop="name" label="账号" width="150"></el-table-column>
          <el-table-column label="今日使用" width="100" align="center">
            <template slot-scope="scope">
              {{ scope.row.today_used }} / {{ scope.row.daily_limit }}
            </template>
          </el-table-column>
          <el-table-column label="剩余" width="80" align="center">
            <template slot-scope="scope">
              <el-tag :type="scope.row.remaining > 0 ? 'success' : 'info'" size="small">
                {{ scope.row.remaining }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="状态" width="80" align="center">
            <template slot-scope="scope">
              <el-tag :type="scope.row.available ? 'success' : 'info'" size="small">
                {{ scope.row.available ? '可用' : '已满' }}
              </el-tag>
            </template>
          </el-table-column>
        </el-table>
        
        <el-alert v-if="accountStatus.total_available_quota < shots.length" type="warning" :closable="false">
          配额不足，请稍后再试或联系管理员增加账号
        </el-alert>
      </div>
      
      <span slot="footer">
        <el-button @click="showBatchVideo = false">取消</el-button>
        <el-button 
          type="primary" 
          :loading="generatingBatch"
          :disabled="!accountStatus || accountStatus.total_available_quota < shots.length"
          @click="handleBatchGenerate"
        >
          开始生成
        </el-button>
      </span>
    </el-dialog>
  </div>
</template>

<script>
import { api } from '@/api'

export default {
  name: 'ShotWorkbench',
  data() {
    return {
      projectId: '',
      project: null,
      loading: false,
      splitting: false,
      shots: [],
      splitText: '',
      showBatchVideo: false,
      accountStatus: null,
      generatingBatch: false
    }
  },
  async mounted() {
    this.projectId = this.$route.params.projectId
    await this.loadProject()
    await this.loadShots()
  },
  methods: {
    async loadProject() {
      try {
        this.project = await api.project.get(this.projectId)
        this.splitText = this.project.novel_content || ''
      } catch (error) {
        console.error('加载项目失败:', error)
      }
    },
    
    async loadShots() {
      this.loading = true
      try {
        this.shots = await api.shot.list(this.projectId)
      } catch (error) {
        console.error('加载分镜失败:', error)
      } finally {
        this.loading = false
      }
    },
    
    async handleSplit() {
      if (!this.splitText.trim()) {
        this.$message.warning('请输入小说段落')
        return
      }
      
      this.splitting = true
      try {
        const res = await api.shot.split({
          project_id: this.projectId,
          novel_paragraph: this.splitText
        })
        this.$message.success(res.message)
        await this.loadShots()
      } catch (error) {
        console.error('拆分失败:', error)
      } finally {
        this.splitting = false
      }
    },
    
    async handleUpdate(shot) {
      try {
        await api.shot.update(shot.id, {
          text: shot.text,
          prompt: shot.prompt,
          neg_prompt: shot.neg_prompt,
          duration: shot.duration
        })
      } catch (error) {
        console.error('更新分镜失败:', error)
      }
    },
    
    async handleGenerateImage(shot) {
      if (!shot.prompt) {
        this.$message.warning('请先填写提示词')
        return
      }
      
      this.$set(shot, 'generating', true)
      try {
        const res = await api.image.generate({
          shot_id: shot.id,
          prompt: shot.prompt,
          neg_prompt: shot.neg_prompt
        })
        shot.img_path = res.data.img_path
        this.$message.success('图片生成成功')
      } catch (error) {
        console.error('生成图片失败:', error)
      } finally {
        this.$set(shot, 'generating', false)
      }
    },
    
    async handleGenerateTTS(shot) {
      if (!shot.text) {
        this.$message.warning('请先填写台词')
        return
      }
      
      this.$set(shot, 'generatingAudio', true)
      try {
        const res = await api.tts.generate({
          shot_id: shot.id,
          text: shot.text,
          voice_name: 'zh_female_qingxin'
        })
        shot.audio_path = res.data.audio_path
        this.$message.success('语音生成成功')
      } catch (error) {
        console.error('生成语音失败:', error)
      } finally {
        this.$set(shot, 'generatingAudio', false)
      }
    },
    
    handleDeleteShot(shot) {
      this.$confirm('确定删除该分镜吗？', '提示', {
        confirmButtonText: '确定',
        cancelButtonText: '取消',
        type: 'warning'
      }).then(async () => {
        try {
          await api.shot.delete(shot.id)
          this.$message.success('删除成功')
          await this.loadShots()
        } catch (error) {
          console.error('删除分镜失败:', error)
        }
      }).catch(() => {})
    },
    
    async handleExportSRT() {
      try {
        const res = await api.tts.exportSrt(this.projectId)
        this.$message.success(res.message)
        
        // 下载SRT文件
        const downloadUrl = api.tts.downloadSrt(this.projectId)
        window.open(downloadUrl, '_blank')
      } catch (error) {
        console.error('导出SRT失败:', error)
      }
    },
    
    async showBatchVideoDialog() {
      if (!this.shots || this.shots.length === 0) {
        this.$message.warning('没有可用的分镜')
        return
      }
      
      this.showBatchVideo = true
      
      // 加载账号状态
      try {
        const res = await api.video.getAccountStatus()
        this.accountStatus = res.data
      } catch (error) {
        console.error('加载账号状态失败:', error)
        this.$message.error('加载账号状态失败')
      }
    },
    
    async handleBatchGenerate() {
      this.generatingBatch = true
      
      try {
        const res = await api.video.generateBatch(this.projectId, null)
        
        // 显示详细结果
        const results = res.data.results || []
        let message = `批量生成完成\n总计：${res.data.total_shots} 条\n成功：${res.data.success_count} 条\n失败：${res.data.failed_count} 条\n\n`
        
        results.forEach(r => {
          message += `${r.account_name}: 成功 ${r.success_count}, 失败 ${r.failed_count}\n`
        })
        
        this.$alert(message, '生成结果', {
          confirmButtonText: '确定',
          type: res.data.failed_count > 0 ? 'warning' : 'success'
        })
        
        this.showBatchVideo = false
        
      } catch (error) {
        console.error('批量生成失败:', error)
      } finally {
        this.generatingBatch = false
      }
    },
    
    async handleRegenerateVideo(shot) {
      this.$confirm('确定重新生成该分镜的视频吗？', '提示', {
        confirmButtonText: '确定',
        cancelButtonText: '取消',
        type: 'warning'
      }).then(async () => {
        try {
          const res = await api.video.generateSingle(shot.id, null)
          this.$message.success(res.message)
        } catch (error) {
          console.error('重新生成失败:', error)
        }
      }).catch(() => {})
    },
    
    getStaticUrl(path) {
      return api.staticUrl(path)
    }
  }
}
</script>

<style scoped>
.shot-workbench-container {
  min-height: 100vh;
  background: var(--bg-dark-primary);
  position: relative;
}

.shot-workbench-container::before {
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
  position: relative;
  z-index: 1;
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
  position: relative;
  z-index: 1;
}

.control-card {
  margin-bottom: 24px;
}

.el-card {
  border-radius: var(--radius-md);
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4);
  border: 1px solid rgba(255, 255, 255, 0.1);
}

.el-card >>> .el-card__header {
  background: rgba(255, 255, 255, 0.05);
  border-bottom: 1px solid rgba(255, 255, 255, 0.1);
  font-weight: 600;
  color: var(--text-light);
}

.el-card >>> .el-card__body {
  padding: 24px;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.el-table {
  border-radius: var(--radius);
}

.el-table >>> th {
  background: rgba(255, 255, 255, 0.05);
  color: var(--text-light);
  font-weight: 600;
}

.el-table >>> .el-button--text {
  color: var(--primary-light);
  font-weight: 500;
}

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
</style>
