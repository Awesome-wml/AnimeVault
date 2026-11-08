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
          <el-button type="primary" size="mini" @click="handleConvertScript" :loading="scriptLoading" style="margin-left:8px">
            📝 转剧本{{ scriptLoading && scriptChars ? `（接收 ${scriptChars} 字）` : '' }}
          </el-button>
        </span>
      </div>

      <div class="extract-bar">
        <div class="extract-row">
          <span class="extract-tag">剧本转换</span>
          <span class="field-label">模型</span>
          <el-select v-model="scriptModelId" placeholder="选择转剧本模型（默认）" clearable style="width:280px">
            <el-option-group v-for="group in modelGroups" :key="group.provider" :label="group.label">
              <el-option v-for="opt in group.items" :key="opt.key" :label="opt.label" :value="opt.key"></el-option>
            </el-option-group>
          </el-select>
          <span class="field-label">提示词</span>
          <el-select v-model="scriptPromptId" placeholder="剧本转换提示词（默认）" clearable style="width:300px">
            <el-option v-for="p in scriptPrompts" :key="p._id" :label="p.name" :value="p._id"></el-option>
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

    <!-- 剧本场次 -->
    <el-card class="script-card" v-loading="scriptLoading" style="margin-top:16px">
      <div slot="header">
        <span>🎭 剧本场次（{{ scripts.length }}）</span>
      </div>
      <div v-if="!scripts.length" class="script-empty">暂无剧本，先在上方「转剧本」生成分场脚本，再提取资产与拆分镜</div>
      <div v-for="sc in scripts" :key="sc.id" class="script-scene">
        <div class="scene-head">
          <span class="scene-no">场次{{ sc.scene_no }}</span>
          <span class="scene-loc">{{ sc.location }}</span>
          <span v-if="sc.time" class="scene-time">{{ sc.time }}</span>
          <span class="scene-chars">出场：{{ (sc.characters || []).join('、') }}</span>
          <span style="float: right">
            <el-button size="mini" text @click="toggleEditScript(sc)">{{ editingScript[sc.id] ? '完成' : '编辑' }}</el-button>
            <el-button size="mini" text style="color: #f56c6c" @click="handleDeleteScript(sc)">删除</el-button>
          </span>
        </div>
        <template v-if="!editingScript[sc.id]">
          <div v-for="(d, i) in sc.dialogues" :key="i" class="scene-line"><b>{{ d.speaker }}：</b>{{ d.line }}</div>
          <div v-if="sc.action" class="scene-action">动作/环境：{{ sc.action }}</div>
          <div v-if="sc.beat" class="scene-beat">节拍：{{ sc.beat }}</div>
        </template>
        <template v-else>
          <el-input v-model="sc.location" size="small" placeholder="地点" style="margin-bottom: 6px"></el-input>
          <el-input v-model="sc.action" type="textarea" :rows="2" size="small" placeholder="动作/环境" style="margin-bottom: 6px"></el-input>
          <el-input v-model="sc.beat" size="small" placeholder="节拍/情绪" style="margin-bottom: 6px"></el-input>
          <el-button size="mini" type="primary" @click="handleSaveScript(sc)">保存场次</el-button>
        </template>
      </div>
    </el-card>

    <!-- 资产与分镜提取 -->
    <el-card class="extract-card" style="margin-top:16px">
      <div slot="header">
        <span>🎬 资产与分镜提取</span>
        <span style="float: right">
          <el-button type="primary" size="mini" @click="handleOneClick" :loading="oneClickLoading">
            ✨ 一键提取{{ oneClickLoading && (extractChars || splitChars) ? `（接收 ${extractChars || splitChars} 字）` : '' }}
          <el-button type="primary" size="mini" @click="handleConvertScript" :loading="scriptLoading" style="margin-left:8px">
            📝 转剧本
          </el-button>
        </span>
      </div>

      <el-input
        v-model="novelContent"
        type="textarea"
        :rows="28"
        placeholder="粘贴小说内容到这里，或点击上方「AI生成」自动创作..."
      ></el-input>
    </el-card>

    <!-- 剧本场次 -->
    <el-card class="script-card" v-loading="scriptLoading" style="margin-top:16px">
      <div slot="header">
        <span>🎭 剧本场次（{{ scripts.length }}）</span>
      </div>
      <div v-if="!scripts.length" class="script-empty">暂无剧本，先在上方「转剧本」生成分场脚本，再提取资产与拆分镜</div>
      <div v-for="sc in scripts" :key="sc.id" class="script-scene">
        <div class="scene-head">
          <span class="scene-no">场次{{ sc.scene_no }}</span>
          <span class="scene-loc">{{ sc.location }}</span>
          <span v-if="sc.time" class="scene-time">{{ sc.time }}</span>
          <span class="scene-chars">出场：{{ (sc.characters || []).join('、') }}</span>
          <span style="float: right">
            <el-button size="mini" text @click="toggleEditScript(sc)">{{ editingScript[sc.id] ? '完成' : '编辑' }}</el-button>
            <el-button size="mini" text style="color: #f56c6c" @click="handleDeleteScript(sc)">删除</el-button>
          </span>
        </div>
        <template v-if="!editingScript[sc.id]">
          <div v-for="(d, i) in sc.dialogues" :key="i" class="scene-line"><b>{{ d.speaker }}：</b>{{ d.line }}</div>
          <div v-if="sc.action" class="scene-action">动作/环境：{{ sc.action }}</div>
          <div v-if="sc.beat" class="scene-beat">节拍：{{ sc.beat }}</div>
        </template>
        <template v-else>
          <el-input v-model="sc.location" size="small" placeholder="地点" style="margin-bottom: 6px"></el-input>
          <el-input v-model="sc.action" type="textarea" :rows="2" size="small" placeholder="动作/环境" style="margin-bottom: 6px"></el-input>
          <el-input v-model="sc.beat" size="small" placeholder="节拍/情绪" style="margin-bottom: 6px"></el-input>
          <el-button size="mini" type="primary" @click="handleSaveScript(sc)">保存场次</el-button>
        </template>
      </div>
    </el-card>

    <!-- 资产与分镜提取 -->
    <el-card class="extract-card" style="margin-top:16px">
      <div slot="header">
        <span>🎬 资产与分镜提取</span>
        <span style="float: right">
          <el-button type="primary" size="mini" @click="handleOneClick" :loading="oneClickLoading">
            ✨ 一键提取（角色/道具/场景/分镜）
          </el-button>
          <el-button type="success" size="mini" @click="handleSplitOnly" :loading="splitLoading" style="margin-left:8px">
            🎬 仅拆分镜{{ splitLoading && splitChars ? `（接收 ${splitChars} 字）` : '' }}
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
      scriptLoading: false,
      scripts: [],
      editingScript: {},
      scriptChars: 0,
      extractChars: 0,
      splitChars: 0,
      scriptLoading: false,
      scripts: [],
      editingScript: {},
      novelContent: '',
      novelPrompts: [],
      activeCollapse: [],
      // 提取参数
      modelList: [],
      extractModelId: '',
      splitModelId: '',
      scriptModelId: '',
      extractPrompts: [],
      extractPromptId: '',
      splitPrompts: [],
      splitPromptId: '',
      scriptPrompts: [],
      scriptPromptId: '',
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
      await this.loadScripts()
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
          this.scriptModelId = this.extractModelId
        }
      } catch (e) {
        console.error('model list error:', e)
      }
      // 提取类提示词（剧本转换 / 资产提取 / 分镜拆分；本流派 + 通用）
      try {
        const er = await api.prompt.list('')
        this.scriptPrompts = (er.data || []).filter(
          p => p.type === 'script_convert' && this.matchCategory(p)
        )
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

    async loadScripts() {
      try {
        const res = await api.script.list(this.projectId)
        this.scripts = (res.data && res.data.scripts) || []
      } catch (error) {
        console.error('加载剧本失败:', error)
      }
    },

    async handleConvertScript() {
      if (!this.novelContent.trim()) {
        this.$message.warning('请先粘贴小说内容')
        return
      }
      this.scriptLoading = true
      this.scriptChars = 0
      const [recordId, ...modelParts] = (this.scriptModelId || '').split('::')
      try {
        await api.ssePost('/api/scripts/convert', {
          project_id: this.projectId,
          novel_text: this.novelContent,
          model_id: recordId || '',
          model: modelParts.join('::') || '',
          prompt_id: this.scriptPromptId || ''
        }, {
          onProgress: (chars) => { this.scriptChars = chars },
          onDone: async (payload) => {
            await this.loadScripts()
            this.$message.success(payload.message || '剧本转换完成')
          },
          onError: (payload) => this.$message.error(payload.message || '转剧本失败')
        })
      } catch (error) {
        console.error('转剧本失败:', error)
        this.$message.error('转剧本失败，请查看控制台')
      } finally {
        this.scriptLoading = false
      }
    },

    toggleEditScript(sc) {
      this.$set(this.editingScript, sc.id, !this.editingScript[sc.id])
    },

    async handleSaveScript(sc) {
      try {
        await api.script.update(sc.id, {
          location: sc.location,
          action: sc.action,
          beat: sc.beat,
          characters: sc.characters,
          dialogues: sc.dialogues
        })
        this.$set(this.editingScript, sc.id, false)
        this.$message.success('场次已保存')
      } catch (error) {
        console.error('保存场次失败:', error)
        this.$message.error('保存场次失败')
      }
    },

    async handleDeleteScript(sc) {
      try {
        await api.script.delete(sc.id)
        this.scripts = this.scripts.filter(s => s.id !== sc.id)
        this.$message.success('场次已删除')
      } catch (error) {
        console.error('删除场次失败:', error)
        this.$message.error('删除场次失败')
      }
    },

    async loadScripts() {
      try {
        const res = await api.script.list(this.projectId)
        this.scripts = (res.data && res.data.scripts) || []
      } catch (error) {
        console.error('加载剧本失败:', error)
      }
    },

    async handleConvertScript() {
      if (!this.novelContent.trim()) {
        this.$message.warning('请先粘贴小说内容')
        return
      }
      this.scriptLoading = true
      const [recordId, ...modelParts] = (this.extractModelId || '').split('::')
      try {
        this.$message.info('正在把小说转成分场剧本...')
        await api.script.convert({
          project_id: this.projectId,
          novel_text: this.novelContent,
          model_id: recordId || '',
          model: modelParts.join('::') || '',
          prompt_id: ''
        })
        await this.loadScripts()
        this.$message.success(`剧本转换完成：${this.scripts.length} 场`)
      } catch (error) {
        console.error('转剧本失败:', error)
        this.$message.error('转剧本失败，请查看控制台')
      } finally {
        this.scriptLoading = false
      }
    },

    toggleEditScript(sc) {
      this.$set(this.editingScript, sc.id, !this.editingScript[sc.id])
    },

    async handleSaveScript(sc) {
      try {
        await api.script.update(sc.id, {
          location: sc.location,
          action: sc.action,
          beat: sc.beat,
          characters: sc.characters,
          dialogues: sc.dialogues
        })
        this.$set(this.editingScript, sc.id, false)
        this.$message.success('场次已保存')
      } catch (error) {
        console.error('保存场次失败:', error)
        this.$message.error('保存场次失败')
      }
    },

    async handleDeleteScript(sc) {
      try {
        await api.script.delete(sc.id)
        this.scripts = this.scripts.filter(s => s.id !== sc.id)
        this.$message.success('场次已删除')
      } catch (error) {
        console.error('删除场次失败:', error)
        this.$message.error('删除场次失败')
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
      this.splitChars = 0
      const [sRecordId, ...sModelParts] = (this.splitModelId || '').split('::')
      const splitModelOpts = { model_id: sRecordId || '', model: sModelParts.join('::') || '' }
      try {
        await api.ssePost('/api/shots/split', {
          project_id: this.projectId,
          novel_paragraph: this.novelContent,
          ...splitModelOpts,
          prompt_id: this.splitPromptId || '',
          video_set_id: this.videoSetId || ''
        }, {
          onProgress: (chars) => { this.splitChars = chars },
          onDone: (payload) => this.$message.success(payload.message || '拆分镜完成'),
          onError: (payload) => this.$message.error(payload.message || '拆分镜失败')
        })
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
      this.extractChars = 0
      this.splitChars = 0
      const [recordId, ...modelParts] = (this.extractModelId || '').split('::')
      const extractModelOpts = { model_id: recordId || '', model: modelParts.join('::') || '' }
      const [sRecordId, ...sModelParts] = (this.splitModelId || '').split('::')
      const splitModelOpts = { model_id: sRecordId || '', model: sModelParts.join('::') || '' }
      const extractOpts = { ...extractModelOpts, prompt_id: this.extractPromptId || '' }
      try {
        await api.ssePost('/api/assets/extract-all', {
          project_id: this.projectId,
          novel_text: this.novelContent,
          ...extractOpts
        }, {
          onProgress: (chars) => { this.extractChars = chars },
          onDone: (payload) => this.$message.success(payload.message || '资产提取完成'),
          onError: (payload) => { throw new Error(payload.message || '资产提取失败') }
        })

        await api.ssePost('/api/shots/split', {
          project_id: this.projectId,
          novel_paragraph: this.novelContent,
          ...splitModelOpts,
          prompt_id: this.splitPromptId || '',
          video_set_id: this.videoSetId || ''
        }, {
          onProgress: (chars) => { this.splitChars = chars },
          onDone: (payload) => this.$message.success(payload.message || '拆分镜完成'),
          onError: (payload) => { throw new Error(payload.message || '拆分镜失败') }
        })

        this.$message.success('一键提取完成！已生成角色、道具、场景和分镜')
      } catch (error) {
        console.error('一键提取失败:', error)
        this.$message.error(error.message || '部分步骤失败，请查看控制台')
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

.script-card {
  background: rgba(30, 41, 59, 0.6);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: var(--radius-md);
}

.script-card >>> .el-card__header {
  background: rgba(255, 255, 255, 0.05);
  border-bottom: 1px solid rgba(255, 255, 255, 0.1);
  font-weight: 600;
  color: var(--text-light);
}

.extract-card {
  background: rgba(30, 41, 59, 0.6);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: var(--radius-md);
}

.extract-card >>> .el-card__header {
  background: rgba(255, 255, 255, 0.05);
  border-bottom: 1px solid rgba(255, 255, 255, 0.1);
  font-weight: 600;
  color: var(--text-light);
}

.script-empty {
  color: #909399;
  font-size: 13px;
  padding: 12px 0;
}

.script-scene {
  padding: 10px 0;
  border-bottom: 1px dashed rgba(255, 255, 255, 0.1);
}

.script-scene:last-child {
  border-bottom: none;
}

.scene-head {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 6px;
}

.scene-no {
  font-weight: 700;
  color: #67e8f9;
}

.scene-loc {
  color: #e0e7ff;
  font-weight: 600;
}

.scene-time {
  color: #909399;
  font-size: 12px;
}

.scene-chars {
  color: #c7d2fe;
  font-size: 12px;
}

.scene-line {
  font-size: 13px;
  line-height: 1.7;
  color: #cbd5e1;
}

.scene-line b {
  color: #fbbf24;
}

.scene-action,
.scene-beat {
  font-size: 12px;
  color: #94a3b8;
  line-height: 1.6;
  margin-top: 2px;
}
</style>
