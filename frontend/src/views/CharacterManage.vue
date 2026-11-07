<template>
  <div class="character-manage-container">
    <el-container>
      <el-header>
        <div class="header-content">
          <el-button icon="el-icon-back" @click="$router.back()">返回</el-button>
          <h3>{{ project ? project.name : '加载中...' }} - 角色管理</h3>
          <div></div>
        </div>
      </el-header>
      
      <el-main>
        <el-card>
          <div slot="header" class="card-header">
            <span>角色列表</span>
            <div>
              <el-button type="success" size="small" icon="el-icon-magic-stick" @click="showExtractDialog = true">AI提取角色</el-button>
              <el-button type="primary" size="small" icon="el-icon-plus" @click="showAddDialog = true">手动添加</el-button>
            </div>
          </div>
          
          <el-table :data="characters" v-loading="loading">
            <el-table-column prop="name" label="角色名" width="150"></el-table-column>
            <el-table-column prop="description" label="外貌人设" min-width="300"></el-table-column>
            <el-table-column label="TTS音色" width="180">
              <template slot-scope="scope">
                <el-select v-model="scope.row.voice_name" placeholder="选择音色" size="small" @change="handleVoiceChange(scope.row)">
                  <el-option v-for="voice in voices" :key="voice.name" :label="voice.display_name" :value="voice.name"></el-option>
                </el-select>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="150">
              <template slot-scope="scope">
                <el-button type="text" size="small" @click="handleEdit(scope.row)">编辑</el-button>
                <el-button type="text" size="small" @click="handleDelete(scope.row)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-main>
    </el-container>
    
    <!-- AI提取角色对话框 -->
    <el-dialog title="AI提取角色" :visible.sync="showExtractDialog" width="700px">
      <el-form label-width="100px">
        <el-form-item label="小说文本">
          <el-input v-model="extractText" type="textarea" :rows="12" placeholder="粘贴小说文本，AI将自动提取角色"></el-input>
        </el-form-item>
        <el-alert type="info" :closable="false">
          AI将从文本中提取3-10个主要角色及其外貌特征
        </el-alert>
      </el-form>
      <span slot="footer">
        <el-button @click="showExtractDialog = false">取消</el-button>
        <el-button type="primary" :loading="extracting" @click="handleExtract">提取</el-button>
      </span>
    </el-dialog>
    
    <!-- 添加/编辑角色对话框 -->
    <el-dialog :title="editingCharacter ? '编辑角色' : '添加角色'" :visible.sync="showAddDialog" width="600px">
      <el-form :model="characterForm" label-width="100px">
        <el-form-item label="角色名">
          <el-input v-model="characterForm.name" placeholder="请输入角色名"></el-input>
        </el-form-item>
        <el-form-item label="外貌人设">
          <el-input v-model="characterForm.description" type="textarea" :rows="4" placeholder="描述角色的外貌特征、性格等"></el-input>
        </el-form-item>
        <el-form-item label="TTS音色">
          <el-select v-model="characterForm.voice_name" placeholder="选择音色">
            <el-option v-for="voice in voices" :key="voice.name" :label="voice.display_name" :value="voice.name"></el-option>
          </el-select>
        </el-form-item>
      </el-form>
      <span slot="footer">
        <el-button @click="showAddDialog = false">取消</el-button>
        <el-button type="primary" @click="handleSaveCharacter">保存</el-button>
      </span>
    </el-dialog>
  </div>
</template>

<script>
import { api } from '@/api'

export default {
  name: 'CharacterManage',
  data() {
    return {
      projectId: '',
      project: null,
      loading: false,
      characters: [],
      voices: [],
      showExtractDialog: false,
      showAddDialog: false,
      extracting: false,
      extractText: '',
      editingCharacter: null,
      characterForm: {
        name: '',
        description: '',
        voice_name: null
      }
    }
  },
  async mounted() {
    this.projectId = this.$route.params.projectId
    await this.loadProject()
    await this.loadCharacters()
    await this.loadVoices()
  },
  methods: {
    async loadProject() {
      try {
        this.project = await api.project.get(this.projectId)
        this.extractText = this.project.novel_content || ''
      } catch (error) {
        console.error('加载项目失败:', error)
      }
    },
    
    async loadCharacters() {
      this.loading = true
      try {
        this.characters = await api.character.list(this.projectId)
      } catch (error) {
        console.error('加载角色失败:', error)
      } finally {
        this.loading = false
      }
    },
    
    async loadVoices() {
      try {
        const res = await api.tts.getVoices()
        this.voices = res.data.voices
      } catch (error) {
        console.error('加载音色列表失败:', error)
      }
    },
    
    async handleExtract() {
      if (!this.extractText.trim()) {
        this.$message.warning('请输入小说文本')
        return
      }
      
      this.extracting = true
      try {
        const res = await api.character.extract({
          project_id: this.projectId,
          novel_text: this.extractText
        })
        this.$message.success(res.message)
        this.showExtractDialog = false
        await this.loadCharacters()
      } catch (error) {
        console.error('提取角色失败:', error)
      } finally {
        this.extracting = false
      }
    },
    
    handleEdit(character) {
      this.editingCharacter = character
      this.characterForm = {
        name: character.name,
        description: character.description,
        voice_name: character.voice_name
      }
      this.showAddDialog = true
    },
    
    async handleSaveCharacter() {
      if (!this.characterForm.name) {
        this.$message.warning('请输入角色名')
        return
      }
      
      try {
        if (this.editingCharacter) {
          await api.character.update(this.editingCharacter.id, this.characterForm)
          this.$message.success('更新成功')
        } else {
          await api.character.create({
            project_id: this.projectId,
            ...this.characterForm
          })
          this.$message.success('添加成功')
        }
        
        this.showAddDialog = false
        this.editingCharacter = null
        this.characterForm = { name: '', description: '', voice_name: null }
        await this.loadCharacters()
      } catch (error) {
        console.error('保存角色失败:', error)
      }
    },
    
    async handleVoiceChange(character) {
      try {
        await api.character.update(character.id, { voice_name: character.voice_name })
        this.$message.success('音色已更新')
      } catch (error) {
        console.error('更新音色失败:', error)
      }
    },
    
    handleDelete(character) {
      this.$confirm(`确定删除角色"${character.name}"吗？`, '提示', {
        confirmButtonText: '确定',
        cancelButtonText: '取消',
        type: 'warning'
      }).then(async () => {
        try {
          await api.character.delete(character.id)
          this.$message.success('删除成功')
          await this.loadCharacters()
        } catch (error) {
          console.error('删除角色失败:', error)
        }
      }).catch(() => {})
    }
  }
}
</script>

<style scoped>
.character-manage-container {
  min-height: 100vh;
  background: var(--bg-dark-primary);
  position: relative;
}

.character-manage-container::before {
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

>>> .el-form-item__label {
  font-weight: 500;
  color: var(--text-light);
}

>>> .el-alert {
  border-radius: var(--radius);
}
</style>
