<template>
  <div class="asset-panel">
    <!-- 项目风格 -->
    <el-card class="style-card" v-if="project">
      <div slot="header"><span>项目风格</span></div>
      <el-form inline>
        <el-form-item label="题材">
          <el-select v-model="styleGenre" placeholder="选择题材" style="width:200px" @change="onStyleChange">
            <el-option v-for="s in styleOptions" :key="s.id" :label="s.name" :value="s.id"></el-option>
          </el-select>
        </el-form-item>
        <el-form-item label="风格说明">
          <span class="style-desc">{{ currentStyle ? currentStyle.desc : '未选择风格' }}</span>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" size="small" @click="saveStyle">保存风格</el-button>
        </el-form-item>
      </el-form>
      <el-alert type="info" :closable="false" class="style-tip">
        风格会贯穿整部短剧：AI 提取角色/道具/场景、生成三视图参考图、拆分分镜和文生图都会遵循该风格。
      </el-alert>
    </el-card>

    <!-- 资产分类 Tabs -->
    <el-card>
      <el-tabs v-model="activeTab">
        <!-- 角色 -->
        <el-tab-pane label="角色" name="character">
          <div class="tab-header">
            <el-button type="success" size="small" icon="el-icon-magic-stick" @click="showExtractDialog('character')">AI提取角色</el-button>
            <el-button type="primary" size="small" icon="el-icon-plus" @click="openAddDialog('character')">手动添加</el-button>
            <el-button type="warning" size="small" icon="el-icon-headset" :loading="assigningVoice" @click="autoAssignVoice">AI自动关联音色</el-button>
          </div>
          <el-table :data="characters" v-loading="loadingChar">
            <el-table-column label="三视图" width="110">
              <template slot-scope="scope">
                <img v-if="scope.row.image_path" :src="getStaticUrl(scope.row.image_path)" class="thumb" />
                <span v-else class="no-img">未生成</span>
              </template>
            </el-table-column>
            <el-table-column prop="name" label="角色名" width="120"></el-table-column>
            <el-table-column prop="description" label="外貌人设" min-width="240"></el-table-column>
            <el-table-column label="音色" width="170">
              <template slot-scope="scope">
                <el-select v-model="scope.row.voice_name" size="small" placeholder="选音色" @change="changeVoice(scope.row)">
                  <el-option v-for="v in voices" :key="v.name" :label="v.display_name + '（' + (v.age_group||'') + '）'" :value="v.name"></el-option>
                </el-select>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="260">
              <template slot-scope="scope">
                <el-button type="text" size="small" :disabled="!!genLoading" @click="generateAsset('character', scope.row)">生成三视图</el-button>
                <el-button type="text" size="small" @click="triggerUpload('character', scope.row)">上传三视图</el-button>
                <el-button type="text" size="small" @click="handleEdit(scope.row)">编辑</el-button>
                <el-button type="text" size="small" @click="handleDelete('character', scope.row)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>

        <!-- 道具 -->
        <el-tab-pane label="道具" name="prop">
          <div class="tab-header">
            <el-button type="success" size="small" icon="el-icon-magic-stick" @click="showExtractDialog('prop')">AI提取道具</el-button>
            <el-button type="primary" size="small" icon="el-icon-plus" @click="openAddDialog('prop')">手动添加</el-button>
          </div>
          <el-table :data="props" v-loading="loadingProp">
            <el-table-column label="参考图" width="130">
              <template slot-scope="scope">
                <img v-if="scope.row.image_path" :src="getStaticUrl(scope.row.image_path)" class="thumb" />
                <span v-else class="no-img">未生成</span>
              </template>
            </el-table-column>
            <el-table-column prop="name" label="道具名" width="140"></el-table-column>
            <el-table-column prop="prop_type" label="类型" width="120"></el-table-column>
            <el-table-column prop="description" label="描述" min-width="280"></el-table-column>
            <el-table-column label="操作" width="300">
              <template slot-scope="scope">
                <el-button type="text" size="small" :loading="genLoading===('prop_'+scope.row.id)" @click="generateAsset('prop', scope.row)">生成参考图</el-button>
                <el-button type="text" size="small" @click="triggerUpload('prop', scope.row)">上传参考图</el-button>
                <el-button type="text" size="small" @click="handleEdit(scope.row)">编辑</el-button>
                <el-button type="text" size="small" @click="handleDelete('prop', scope.row)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>

        <!-- 场景 -->
        <el-tab-pane label="场景" name="scene">
          <div class="tab-header">
            <el-button type="success" size="small" icon="el-icon-magic-stick" @click="showExtractDialog('scene')">AI提取场景</el-button>
            <el-button type="primary" size="small" icon="el-icon-plus" @click="openAddDialog('scene')">手动添加</el-button>
          </div>
          <el-table :data="scenes" v-loading="loadingScene">
            <el-table-column label="参考图" width="130">
              <template slot-scope="scope">
                <img v-if="scope.row.image_path" :src="getStaticUrl(scope.row.image_path)" class="thumb" />
                <span v-else class="no-img">未生成</span>
              </template>
            </el-table-column>
            <el-table-column prop="name" label="场景名" width="140"></el-table-column>
            <el-table-column prop="scene_type" label="类型" width="120"></el-table-column>
            <el-table-column prop="description" label="环境描述" min-width="280"></el-table-column>
            <el-table-column label="操作" width="300">
              <template slot-scope="scope">
                <el-button type="text" size="small" :loading="genLoading===('scene_'+scope.row.id)" @click="generateAsset('scene', scope.row)">生成参考图</el-button>
                <el-button type="text" size="small" @click="triggerUpload('scene', scope.row)">上传参考图</el-button>
                <el-button type="text" size="small" @click="handleEdit(scope.row)">编辑</el-button>
                <el-button type="text" size="small" @click="handleDelete('scene', scope.row)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>
      </el-tabs>
    </el-card>

    <!-- 隐藏文件选择器：用于人工上传三视图/参考图 -->
    <input ref="uploadInput" type="file" accept="image/*" style="display:none" @change="onFileSelected" />

    <!-- AI提取对话框 -->
    <el-dialog :title="extractTitle" :visible.sync="showExtract" width="720px">
      <el-form label-width="100px">
        <el-form-item label="小说文本">
          <el-input v-model="extractText" type="textarea" :rows="12" placeholder="粘贴小说文本，AI将自动提取"></el-input>
        </el-form-item>
        <el-form-item label="使用项目风格">
          <el-switch v-model="useProjectStyle"></el-switch>
          <span class="hint" v-if="useProjectStyle">将按「{{ currentStyle ? currentStyle.name : '当前风格' }}」风格提取</span>
        </el-form-item>
        <el-alert type="info" :closable="false">
          {{ extractHint }}
        </el-alert>
      </el-form>
      <span slot="footer">
        <el-button @click="showExtract = false">取消</el-button>
        <el-button type="primary" :loading="extracting" @click="handleExtract">提取</el-button>
      </span>
    </el-dialog>

    <!-- 添加/编辑对话框 -->
    <el-dialog :title="editTitle" :visible.sync="showAdd" width="600px">
      <el-form :model="form" label-width="100px">
        <el-form-item label="名称">
          <el-input v-model="form.name" placeholder="请输入名称"></el-input>
        </el-form-item>
        <el-form-item label="类型" v-if="activeTab !== 'character'">
          <el-input v-model="form.type" :placeholder="activeTab === 'prop' ? '如：武器、法宝、信物' : '如：室内、室外、宫殿'"></el-input>
        </el-form-item>
        <el-form-item :label="activeTab === 'character' ? '外貌人设' : '描述'">
          <el-input v-model="form.description" type="textarea" :rows="4" :placeholder="activeTab === 'character' ? '描述角色的外貌特征、性格等' : '描述外观/环境特征'"></el-input>
        </el-form-item>
      </el-form>
      <span slot="footer">
        <el-button @click="showAdd = false">取消</el-button>
        <el-button type="primary" @click="handleSave">保存</el-button>
      </span>
    </el-dialog>
  </div>
</template>

<script>
import { api, STYLE_LIBRARY } from '@/api'

export default {
  name: 'AssetPanel',
  props: {
    projectId: { type: String, required: true },
    // 初始 tab：character | prop | scene（新路由 /characters /props /scenes 进入时指定）
    initialTab: { type: String, default: 'character' }
  },
  data() {
    return {
      project: null,
      activeTab: this.initialTab,
      styleGenre: '',
      styleOptions: STYLE_LIBRARY,
      currentStyle: null,

      characters: [],
      props: [],
      scenes: [],
      loadingChar: false,
      loadingProp: false,
      loadingScene: false,

      showExtract: false,
      extracting: false,
      extractType: 'character',
      extractText: '',
      useProjectStyle: true,

      showAdd: false,
      editingItem: null,
      form: { name: '', type: '', description: '' },

      genLoading: '',
      voices: [],
      assigningVoice: false,
      uploading: false,
      uploadTarget: null
    }
  },
  computed: {
    extractTitle() {
      const map = { character: 'AI提取角色', prop: 'AI提取道具', scene: 'AI提取场景' }
      return map[this.extractType]
    },
    extractHint() {
      const map = {
        character: 'AI将按所选风格提取3-10个主要角色及其外貌人设，可用于生成三视图',
        prop: 'AI将按所选风格提取重要道具/物品及其外观特征',
        scene: 'AI将按所选风格提取重要场景/地点及其环境氛围'
      }
      return map[this.extractType]
    },
    editTitle() {
      if (this.editingItem) return '编辑'
      const map = { character: '添加角色', prop: '添加道具', scene: '添加场景' }
      return map[this.activeTab]
    }
  },
  methods: {
    getStaticUrl(path) {
      return api.staticUrl(path)
    },
    async loadProject() {
      try {
        this.project = await api.project.get(this.projectId)
        this.styleGenre = this.project.style || ''
        this.syncStyle()
      } catch (error) {
        console.error('加载项目失败:', error)
      }
    },
    syncStyle() {
      this.currentStyle = this.styleOptions.find(s => s.id === this.styleGenre) || null
    },
    onStyleChange() {
      this.syncStyle()
    },
    async saveStyle() {
      try {
        await api.project.update(this.projectId, {
          genre: this.currentStyle ? this.currentStyle.genre : this.styleGenre,
          style: this.styleGenre
        })
        this.$message.success('风格已保存，将贯穿后续所有生成')
      } catch (e) {
        console.error(e)
      }
    },

    async loadAll() {
      await Promise.all([this.loadCharacters(), this.loadProps(), this.loadScenes()])
    },
    async loadVoices() {
      try {
        const res = await api.tts.getVoices()
        this.voices = res.data.voices
      } catch (e) { console.error(e) }
    },
    async autoAssignVoice() {
      this.assigningVoice = true
      try {
        const res = await api.tts.autoAssign(this.projectId)
        this.$message.success(res.message)
        await this.loadCharacters()
      } catch (e) { console.error('自动关联音色失败:', e) }
      finally { this.assigningVoice = false }
    },
    async changeVoice(character) {
      try {
        await api.character.update(character.id, { voice_name: character.voice_name })
        this.$message.success(character.name + ' 音色已更新')
      } catch (e) { console.error(e) }
    },

    triggerUpload(type, row) {
      this.uploadTarget = { type, row }
      this.$refs.uploadInput.value = ''
      this.$refs.uploadInput.click()
    },
    async onFileSelected(e) {
      const file = e.target.files[0]
      if (!file || !this.uploadTarget) return
      const { type, row } = this.uploadTarget
      this.uploading = true
      try {
        const res = await api.asset.upload(type, row.id, file)
        this.$message.success(res.message || '上传成功')
        if (type === 'character') await this.loadCharacters()
        else if (type === 'prop') await this.loadProps()
        else await this.loadScenes()
      } catch (err) {
        console.error('上传失败:', err)
        this.$message.error(err.response && err.response.data && err.response.data.detail || '上传失败')
      } finally {
        this.uploading = false
        this.uploadTarget = null
      }
    },

    async loadCharacters() {
      this.loadingChar = true
      try { this.characters = await api.character.list(this.projectId) } catch (e) { console.error(e) }
      finally { this.loadingChar = false }
    },
    async loadProps() {
      this.loadingProp = true
      try { this.props = await api.prop.list(this.projectId) } catch (e) { console.error(e) }
      finally { this.loadingProp = false }
    },
    async loadScenes() {
      this.loadingScene = true
      try { this.scenes = await api.scene.list(this.projectId) } catch (e) { console.error(e) }
      finally { this.loadingScene = false }
    },

    showExtractDialog(type) {
      this.extractType = type
      this.extractText = this.project ? this.project.novel_content || '' : ''
      this.showExtract = true
    },
    async handleExtract() {
      if (!this.extractText.trim()) { this.$message.warning('请输入小说文本'); return }
      this.extracting = true
      const style = this.useProjectStyle ? (this.styleGenre || '') : ''
      try {
        const map = {
          character: api.character.extract,
          prop: api.prop.extract,
          scene: api.scene.extract
        }
        const fn = map[this.extractType]
        const res = await fn({
          project_id: this.projectId,
          novel_text: this.extractText,
          style
        })
        this.$message.success(res.message)
        this.showExtract = false
        await this.loadAll()
      } catch (e) {
        console.error('提取失败:', e)
      } finally { this.extracting = false }
    },

    openAddDialog(type) {
      this.activeTab = type
      this.editingItem = null
      this.form = { name: '', type: '', description: '' }
      this.showAdd = true
    },
    handleEdit(item) {
      this.editingItem = item
      this.form = {
        name: item.name,
        type: item.prop_type || item.scene_type || '',
        description: item.description || ''
      }
      this.showAdd = true
    },
    async handleSave() {
      if (!this.form.name) { this.$message.warning('请输入名称'); return }
      const data = {
        project_id: this.projectId,
        name: this.form.name,
        description: this.form.description
      }
      if (this.activeTab === 'prop') data.prop_type = this.form.type
      if (this.activeTab === 'scene') data.scene_type = this.form.type

      try {
        if (this.editingItem) {
          const updateData = { name: this.form.name, description: this.form.description }
          if (this.activeTab === 'prop') updateData.prop_type = this.form.type
          if (this.activeTab === 'scene') updateData.scene_type = this.form.type
          const map = { character: api.character.update, prop: api.prop.update, scene: api.scene.update }
          await map[this.activeTab](this.editingItem.id, updateData)
          this.$message.success('更新成功')
        } else {
          const map = { character: api.character.create, prop: api.prop.create, scene: api.scene.create }
          await map[this.activeTab](data)
          this.$message.success('添加成功')
        }
        this.showAdd = false
        this.editingItem = null
        await this.loadAll()
      } catch (e) { console.error(e) }
    },

    async generateAsset(type, item) {
      if (this.genLoading) {
        this.$message.warning('正在生成图片，请稍候')
        return
      }
      this.genLoading = type + '_' + item.id
      try {
        const res = await api.asset.generate({
          asset_type: type,
          asset_id: item.id,
          style: this.styleGenre || ''
        })
        this.$message.success(res.message + '，已生成')
        await this.loadAll()
      } catch (e) {
        console.error('生成参考图失败:', e)
      } finally { this.genLoading = '' }
    },

    handleDelete(type, item) {
      const label = { character: '角色', prop: '道具', scene: '场景' }[type]
      this.$confirm(`确定删除${label}"${item.name}"吗？`, '提示', {
        confirmButtonText: '确定', cancelButtonText: '取消', type: 'warning'
      }).then(async () => {
        const map = { character: api.character.delete, prop: api.prop.delete, scene: api.scene.delete }
        await map[type](item.id)
        this.$message.success('删除成功')
        await this.loadAll()
      }).catch(() => {})
    }
  },
  async mounted() {
    await this.loadProject()
    await this.loadAll()
    await this.loadVoices()
  }
}
</script>

<style scoped>
.style-card {
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

.style-desc {
  color: var(--text-light);
  font-size: 14px;
  padding: 6px 12px;
  background: rgba(15, 23, 42, 0.5);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: var(--radius);
}

.style-tip {
  margin-top: 16px;
  border-radius: var(--radius);
}

.tab-header {
  display: flex;
  justify-content: flex-end;
  margin-bottom: 20px;
  gap: 12px;
}

.el-table {
  border-radius: var(--radius);
  margin-top: 16px;
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

.thumb {
  width: 90px;
  height: 90px;
  object-fit: cover;
  border-radius: var(--radius);
  border: 1px solid rgba(255, 255, 255, 0.1);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
  transition: var(--transition);
}

.thumb:hover {
  transform: scale(1.05);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.5);
}

.no-img {
  color: var(--text-tertiary);
  font-size: 13px;
  padding: 4px 12px;
  background: rgba(15, 23, 42, 0.5);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: var(--radius-sm);
}

.hint {
  color: var(--text-secondary);
  font-size: 13px;
  margin-left: 12px;
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

>>> .el-tabs__nav-wrap::after {
  background-color: rgba(255, 255, 255, 0.1);
}

>>> .el-tabs__active-bar {
  background-color: var(--primary);
}

>>> .el-tabs__item {
  color: var(--text-tertiary);
  font-weight: 500;
}

>>> .el-tabs__item.is-active {
  color: var(--primary-light);
}

>>> .el-alert {
  border-radius: var(--radius);
}
</style>
