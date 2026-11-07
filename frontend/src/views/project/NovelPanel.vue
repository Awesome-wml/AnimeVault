<template>
  <div class="novel-panel">
    <!-- AI生成（次要功能，置顶折叠，默认收起） -->
    <el-collapse v-model="activeCollapse" class="ai-collapse">
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

          <el-form-item label="提示词模板">
            <el-select v-model="generateForm.prompt_id" placeholder="默认提示词" style="width:100%">
              <el-option v-for="p in novelPrompts" :key="p._id" :label="p.name + ' (' + p.version + ')'" :value="p._id"></el-option>
            </el-select>
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

    <!-- 小说内容编辑区（主功能） -->
    <el-card class="editor-card" v-loading="generating" style="margin-top:16px">
      <div slot="header">
        <span>📖 小说内容</span>
        <span style="float: right; color: #909399; font-size:13px">
          {{ novelContent ? novelContent.length : 0 }} 字
          <el-button type="text" size="mini" @click="handleSave" style="margin-left:16px;color:#67c23a">保存</el-button>
          <el-button type="primary" size="mini" @click="handleOneClick" :loading="oneClickLoading" style="margin-left:8px">
            ✨ 一键提取（角色/道具/场景/分镜）
          </el-button>
          <el-button type="success" size="mini" @click="handleSplitOnly" :loading="splitLoading" style="margin-left:8px">
            🎬 仅拆分镜
          </el-button>
        </span>
      </div>

      <!-- 提取参数：资产提取 / 分镜拆分 两组，各选模型 + 提示词 -->
      <div class="extract-bar">
        <div class="extract-row">
          <span class="extract-tag">资产提取</span>
          <span class="field-label">模型</span>
          <el-select v-model="extractModelId" placeholder="选择提取模型（默认）" clearable style="width:280px">
            <el-option-group v-for="group in modelGroups" :key="group.provider" :label="group.label">
              <el-option v-for="opt in group.items" :key="opt.key" :label="opt.label" :value="opt.key"></el-option>
            </el-option-group>
          </el-select>
          <span class="field-label">提示词</span>
          <el-select v-model="extractPromptId" placeholder="资产提取提示词（角色/道具/场景，默认）" clearable style="width:300px">
            <el-option v-for="p in extractPrompts" :key="p._id" :label="p.name" :value="p._id"></el-option>
          </el-select>
        </div>
        <div class="extract-row">
          <span class="extract-tag">分镜拆分</span>
          <span class="field-label">模型</span>
          <el-select v-model="splitModelId" placeholder="选择分镜模型（默认）" clearable style="width:280px">
            <el-option-group v-for="group in modelGroups" :key="group.provider" :label="group.label">
              <el-option v-for="opt in group.items" :key="opt.key" :label="opt.label" :value="opt.key"></el-option>
            </el-option-group>
          </el-select>
          <span class="field-label">提示词</span>
          <el-select v-model="splitPromptId" placeholder="分镜拆分提示词（默认）" clearable style="width:300px">
            <el-option v-for="p in splitPrompts" :key="p._id" :label="p.name" :value="p._id"></el-option>
          </el-select>
        </div>
      </div>

      <el-input
        v-model="novelContent"
        type="textarea"
        :rows="28"
        placeholder="粘贴小说内容到这里，或点击上方「AI生成」自动创作..."
      ></el-input>
    </el-card>
  </div>
</template>

<script>
import { api, STYLE_LIBRARY } from '@/api'

const PROVIDER_LABELS = {
  zhipu: '智谱 GLM',
  deepseek: 'DeepSeek',
  openai: 'OpenAI',
  gemini: 'Google Gemini',
  other: '其他'
}

export default {
  name: 'NovelPanel',
  props: {
    projectId: { type: String, required: true },
    videoSetId: { type: String, default: '' }
  },
  data() {
    return {
      project: null,
      generating: false,
      oneClickLoading: false,
      splitLoading: false,
      novelContent: '',
      novelPrompts: [],
      activeCollapse: [],
      // 提取参数
      modelList: [],
      extractModelId: '',
      splitModelId: '',
      extractPrompts: [],
      extractPromptId: '',
      splitPrompts: [],
      splitPromptId: '',
      projectGenre: '',
      generateForm: {
        genre: '玄幻',
        style: 'xuanhuan',
        outline: '',
        protagonist: '',
        target_words: 5000,
        prompt_id: ''
      },
      styleOptions: STYLE_LIBRARY,
      currentStyle: STYLE_LIBRARY[0]
    }
  },
  computed: {
    modelGroups() {
      const order = ['zhipu', 'deepseek', 'openai', 'gemini', 'other']
      const map = {}
      this.modelList.forEach(m => {
        const p = m.provider || 'other'
        const models = m.models || (m.model ? [m.model] : [])
        const items = models.map(mid => ({
          key: m._id + '::' + mid,
          label: m.name + '（' + mid + '）',
          recordId: m._id,
          model: mid
        }))
        ;(map[p] = map[p] || []).push(...items)
      })
      const known = order.filter(p => map[p])
      const extra = Object.keys(map).filter(p => !order.includes(p))
      return [...known, ...extra]
        .map(p => ({ provider: p, label: PROVIDER_LABELS[p] || p, items: map[p] }))
    }
  },
  async mounted() {
    // 等projectId有值了再加载
    if (this.projectId) {
      await this.init()
    }
  },
  watch: {
    projectId: {
      immediate: true,
      handler(val) {
        if (val) {
          this.init()
        }
      }
    }
  },
  methods: {
    async init() {
      await this.loadProject()
      // 小说生成提示词（本流派 + 通用）
      try {
        const r = await api.prompt.list('novel')
        this.novelPrompts = (r.data || []).filter(p => this.matchCategory(p))
        const def = this.novelPrompts.find(p => p.is_default)
        this.generateForm.prompt_id = def ? def._id : ''
      } catch (e) {
        console.error('prompt list error:', e)
      }
      // 模型预设
      try {
        const mr = await api.model.list()
        this.modelList = mr.data || []
        const mDef = this.modelList.find(m => m.is_default) || this.modelList[0]
        if (mDef) {
          const ms = mDef.models || (mDef.model ? [mDef.model] : [])
          this.extractModelId = mDef._id + '::' + ms[0]
          this.splitModelId = this.extractModelId
        }
      } catch (e) {
        console.error('model list error:', e)
      }
      // 提取类提示词（资产提取 + 分镜拆分；本流派 + 通用）
      try {
        const er = await api.prompt.list('')
        this.extractPrompts = (er.data || []).filter(
          p => p.type === 'asset_extract' && this.matchCategory(p)
        )
        this.splitPrompts = (er.data || []).filter(
          p => p.type === 'split_shots' && this.matchCategory(p)
        )
      } catch (e) {
        console.error('extract prompt list error:', e)
      }
    },

    matchCategory(p) {
      const c = p.category || '通用'
      return c === '通用' || !this.projectGenre || c === this.projectGenre
    },

    onStyleSelect() {
      this.currentStyle = this.styleOptions.find(s => s.id === this.generateForm.style) || null
      if (this.currentStyle) {
        this.generateForm.genre = this.currentStyle.genre
      }
    },

    async loadProject() {
      try {
        const res = await api.project.get(this.projectId)
        this.project = res
        this.novelContent = res.novel_content || ''
        this.projectGenre = res.genre || ''
      } catch (error) {
        console.error('加载项目失败:', error)
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
          target_words: this.generateForm.target_words,
          prompt_id: this.generateForm.prompt_id,
          token: token
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
    },

    // 一键提取：角色→道具→场景→拆分镜
    async handleSplitOnly() {
      if (!this.novelContent.trim()) {
        this.$message.warning('请先粘贴小说内容')
        return
      }
      this.splitLoading = true
      const [sRecordId, ...sModelParts] = (this.splitModelId || '').split('::')
      const splitModelOpts = { model_id: sRecordId || '', model: sModelParts.join('::') || '' }
      try {
        this.$message.info('正在拆分镜...')
        const r = await api.shot.split({
          project_id: this.projectId,
          novel_paragraph: this.novelContent,
          ...splitModelOpts,
          prompt_id: this.splitPromptId || '',
          video_set_id: this.videoSetId || ''
        })
        const count = (r.data && r.data.count) || 0
        this.$message.success(`拆分镜完成：${count} 个镜头`)
      } catch (error) {
        console.error('拆分镜失败:', error)
        this.$message.error('拆分镜失败，请查看控制台')
      } finally {
        this.splitLoading = false
      }
    },
    async handleOneClick() {
      if (!this.novelContent.trim()) {
        this.$message.warning('请先粘贴小说内容')
        return
      }
      this.oneClickLoading = true
      const [recordId, ...modelParts] = (this.extractModelId || '').split('::')
      const extractModelOpts = { model_id: recordId || '', model: modelParts.join('::') || '' }
      const [sRecordId, ...sModelParts] = (this.splitModelId || '').split('::')
      const splitModelOpts = { model_id: sRecordId || '', model: sModelParts.join('::') || '' }
      const extractOpts = { ...extractModelOpts, prompt_id: this.extractPromptId || '' }
      try {
        this.$message.info('正在提取角色/道具/场景...')
        await api.asset.extractAll({ project_id: this.projectId, novel_text: this.novelContent, ...extractOpts })

        this.$message.info('正在拆分镜...')
        await api.shot.split({
          project_id: this.projectId,
          novel_paragraph: this.novelContent,
          ...splitModelOpts,
          prompt_id: this.splitPromptId || '',
          video_set_id: this.videoSetId || ''
        })

        this.$message.success('一键提取完成！已生成角色、道具、场景和分镜')
      } catch (error) {
        console.error('一键提取失败:', error)
        this.$message.error('部分步骤失败，请查看控制台')
      } finally {
        this.oneClickLoading = false
      }
    }
  }
}
</script>

<style scoped>
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

.extract-bar {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-bottom: 16px;
}

.extract-row {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.extract-tag {
  display: inline-block;
  padding: 3px 10px;
  border-radius: 4px;
  background: #2d4a6e;
  color: #cfe3ff;
  font-size: 13px;
  font-weight: 600;
  white-space: nowrap;
}

.field-label {
  color: #909399;
  font-size: 13px;
  white-space: nowrap;
}

.ai-collapse {
  margin-top: 0;
}
</style>
