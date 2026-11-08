<template>
  <div class="shot-panel">
    <!-- 分镜卡片列表 -->
    <div v-if="shots.length === 0" style="text-align:center;padding:60px;color:#909399;">
      <i class="el-icon-magic-stick" style="font-size:48px;margin-bottom:16px;"></i>
      <div style="font-size:16px;margin-bottom:8px;">还没有分镜</div>
      <div style="font-size:14px;">请先到「小说」页粘贴小说内容，点击「一键提取」自动生成分镜</div>
    </div>
    <div v-else>
    <div class="shot-toolbar">
      <div class="toolbar-title">
        <span>分镜列表</span>
        <el-tag size="small" type="primary" effect="dark">{{ shots.length }} 个镜头</el-tag>
      </div>
      <div class="toolbar-actions">
        <el-select size="small" v-model="imageModelKey" placeholder="文生图模型" style="width:230px">
          <el-option v-for="it in imageModelItems" :key="it.key" :label="it.label" :value="it.key"></el-option>
        </el-select>
        <el-button type="success" size="small" icon="el-icon-download" @click="exportToJianying">导出剪映</el-button>
        <el-button type="primary" size="small" icon="el-icon-video-camera" @click="showBatchVideoDialog">批量生成视频</el-button>
      </div>
    </div>

    <div class="shot-list" v-loading="loading">
      <!-- 空状态 -->
      <div v-if="!loading && shots.length === 0" class="empty-state">
        <div class="empty-icon"><i class="el-icon-film"></i></div>
        <p>还没有分镜，用上方工具拆分小说生成第一个镜头</p>
      </div>

      <!-- 每个分镜一个卡片 -->
      <div v-for="shot in shots" :key="shot.id" class="shot-card">
        <div class="shot-card-head">
          <div class="shot-badge">
            <span class="shot-no">{{ shot.shot_no }}</span>
            <span class="shot-duration"><i class="el-icon-time"></i> {{ shot.duration }}s</span>
          </div>
          <!-- 生成参数站位：模型 / 比例 / 时长（后面再接业务） -->
          <div class="shot-params">
            <el-select size="mini" v-model="shot.model" placeholder="模型" class="param-select">
              <el-option label="Seedance 2.0 Fast" value="seedance_fast"></el-option>
              <el-option label="Seedance 2.5" value="seedance_25"></el-option>
            </el-select>
            <el-select size="mini" v-model="shot.aspect" placeholder="比例" class="param-select">
              <el-option label="16:9 横屏" value="16:9"></el-option>
              <el-option label="9:16 竖屏" value="9:16"></el-option>
            </el-select>
            <el-select size="mini" v-model="shot.duration_choice" placeholder="时长" class="param-select">
              <el-option label="5s" value="5"></el-option>
              <el-option label="10s" value="10"></el-option>
              <el-option label="15s" value="15"></el-option>
            </el-select>
          </div>
          <div class="shot-head-actions">
            <el-tooltip content="从上一个分镜的最后一帧开始，保持画面连贯" placement="top">
              <el-button size="mini" :type="shot.use_prev_frame ? 'primary' : 'info'" plain @click="togglePrevFrame(shot)">
                {{ shot.use_prev_frame ? '关键帧✓' : '关键帧' }}
              </el-button>
            </el-tooltip>
            <el-button size="mini" type="warning" plain icon="el-icon-video-camera" :loading="shot.videoGenerating" @click="handleRegenerateVideo(shot)">
              {{ shot.videoGenerating ? '生成中...' : '生成视频' }}
            </el-button>
            <el-button size="mini" type="danger" plain icon="el-icon-delete" @click="handleDeleteShot(shot)">删除</el-button>
          </div>
        </div>

        <div class="shot-card-body">
          <!-- 左：画面参考图 -->
          <div class="shot-visual">
            <div v-if="shot.img_path" class="shot-img-wrap">
              <el-image
                :src="getStaticUrl(shot.img_path)"
                :preview-src-list="[getStaticUrl(shot.img_path)]"
                fit="cover"
                class="shot-img"
              ></el-image>
              <div class="img-hint"><i class="el-icon-picture"></i> 画面</div>
            </div>
            <div v-else class="shot-img-empty" @click="handleGenerateImage(shot)">
              <i v-if="!shot.generating" class="el-icon-picture-outline empty-icon-big"></i>
              <span v-if="!shot.generating" class="empty-tip">未生成画面</span>
              <i v-if="shot.generating" class="el-icon-loading empty-icon-big"></i>
              <span v-if="shot.generating">生成中...</span>
              <el-button v-if="!shot.generating" size="mini" type="primary" @click.stop="handleGenerateImage(shot)">生成画面</el-button>
            </div>
          </div>

          <!-- 中：台词 + 提示词 + 资产横排 -->
          <div class="shot-info">
            <el-input v-model="shot.text" type="textarea" :rows="2" resize="none" size="small" class="shot-text-input" placeholder="台词 / 旁白" @change="handleUpdate(shot)"></el-input>
            <div class="prompt-block">
              <div v-if="!isEditingPrompt(shot)" class="prompt-view" @dblclick="toggleEditPrompt(shot)">
                <template v-for="(seg, i) in parsePrompt(shot)" :key="i">
                  <span v-if="seg.type === 'text'">{{ seg.text }}</span>
                  <span
                    v-else
                    class="ref-chip"
                    :class="{ missing: !seg.img }"
                    @click="previewRef(shot, seg.num)"
                  >【@图片{{ seg.num }}】</span>
                </template>
              </div>
              <el-input
                v-else
                v-model="shot.video_prompt"
                type="textarea"
                :rows="3"
                size="small"
                class="prompt-input"
                placeholder="豆包自动化提示词"
                @change="onPromptChange(shot)"
              ></el-input>
              <el-button size="mini" text class="prompt-edit-btn" @click="toggleEditPrompt(shot)">
                {{ isEditingPrompt(shot) ? '完成' : '编辑' }}
              </el-button>
            </div>
            <el-input v-model="shot.text" size="small" placeholder="台词 / 旁白" @change="handleUpdate(shot)"></el-input>
            <div class="prompt-block">
              <div v-if="!isEditingPrompt(shot)" class="prompt-view" @dblclick="toggleEditPrompt(shot)">
                <template v-for="(seg, i) in parsePrompt(shot)" :key="i">
                  <span v-if="seg.type === 'text'">{{ seg.text }}</span>
                  <span
                    v-else
                    class="ref-chip"
                    :class="{ missing: !seg.img }"
                    @click="previewRef(shot, seg.num)"
                  >【@图片{{ seg.num }}】</span>
                </template>
              </div>
              <el-input
                v-else
                v-model="shot.video_prompt"
                type="textarea"
                :rows="3"
                size="small"
                class="prompt-input"
                placeholder="豆包自动化提示词"
                @change="onPromptChange(shot)"
              ></el-input>
              <el-button size="mini" text class="prompt-edit-btn" @click="toggleEditPrompt(shot)">
                {{ isEditingPrompt(shot) ? '完成' : '编辑' }}
              </el-button>
            </div>
            <!-- 关联资产：点 chip 可预览大图 -->
            <div class="asset-tags-compact" v-if="shot.assets && shot.assets.length">
              <span class="asset-tag" v-for="(a, i) in shot.assets" :key="i">
                <el-image
                  v-if="a.img"
                  :src="getStaticUrl(a.img)"
                  :preview-src-list="[getStaticUrl(a.img)]"
                  :preview-teleported="true"
                  fit="cover"
                  class="asset-thumb"
                ></el-image>
                <i v-else class="el-icon-picture-outline"></i>
                {{ a.name }}<em v-if="a.label" class="asset-role">{{ a.label }}</em>
              </span>
            </div>
          </div>

          <!-- 右：生成的视频 -->
          <div class="shot-video-col">
            <div v-if="shot.video_path" class="shot-video-wrap">
              <video :src="getStaticUrl(shot.video_path)" controls class="shot-video"></video>
              <div class="img-hint"><i class="el-icon-video-camera"></i> 视频</div>
            </div>
            <!-- 生成中进度 -->
            <div v-else-if="shot.genStep && shot.genStep !== 'done'" class="shot-video-empty">
              <el-progress :percentage="shot.genProgress || 0" :stroke-width="6" style="margin-bottom:8px"></el-progress>
              <div style="font-size:12px;color:#909399;">{{ shot.genMsg || '生成中...' }}</div>
            </div>
            <div v-else class="shot-video-empty">
              <i class="el-icon-video-camera"></i>
              <span>未生成视频</span>
              <el-button size="mini" type="info" plain icon="el-icon-upload2" @click="openManualVideo(shot)">补录视频</el-button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 批量生成视频对话框 -->
    <el-dialog title="批量生成视频（豆包自动化）" :visible.sync="showBatchVideo" width="600px" :close-on-click-modal="false" :modal="false">
      <div v-if="!accountStatus" style="padding: 40px; text-align: center; color: #909399;">
        <i class="el-icon-loading" style="font-size: 24px;"></i> 加载中...
      </div>
      <div v-if="accountStatus">
        <el-alert type="info" :closable="false" style="margin-bottom: 16px">
          <div>总{{ shots.length }} 个分镜，已生成 {{ generatedCount }} 个，待生成 {{ pendingCount }} 个</div>
          <div>今日可用配额：<strong>{{ accountStatus.total_available_quota }}</strong> 条</div>
        </el-alert>

        <div style="margin: 16px 0">
          <span>本次执行：</span>
          <el-input-number v-model="batchRunCount" :min="1" :max="Math.min(pendingCount, accountStatus.total_available_quota)" size="small" style="width: 120px; margin: 0 8px"></el-input-number>
          <span style="color: #999">条（按分镜顺序，跳过已生成的）</span>
        </div>

        <el-table :data="accountStatus.accounts" size="small" border style="margin-bottom: 20px">
          <el-table-column prop="name" label="账号" width="150"></el-table-column>
          <el-table-column label="今日已用" width="100" align="center">
            <template slot-scope="scope">
              {{ scope.row.today_used }}/{{ scope.row.daily_limit }}
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
          <el-table-column label="Cookie 有效期" width="110" align="center">
            <template slot-scope="scope">
              <el-tag :type="cookieTag(scope.row.cookie_days).type" size="small">
                {{ cookieTag(scope.row.cookie_days).text }}
              </el-tag>
            </template>
          </el-table-column>
        </el-table>

        <el-alert v-if="accountStatus.total_available_quota < pendingCount" type="warning" :closable="false">
          今日可用 {{ accountStatus.total_available_quota }} 条，待生成 {{ pendingCount }} 条。本次最多跑 {{ Math.min(accountStatus.total_available_quota, pendingCount) }} 条。
        </el-alert>
      </div>

      <span slot="footer">
        <el-button @click="showBatchVideo = false">取消</el-button>
        <el-button @click="openAccountManage" icon="el-icon-setting">账号管理</el-button>
        <el-button
          type="primary"
          :loading="generatingBatch"
          :disabled="!accountStatus || accountStatus.total_available_quota <= 0 || pendingCount <= 0"
          @click="handleBatchGenerate"
        >
          开始生成
        </el-button>
      </span>
    </el-dialog>

    <!-- 账号管理对话框 -->
    <el-dialog title="豆包账号管理" :visible.sync="showAccountManage" width="900px" @opened="loadAccountList" :close-on-click-modal="false" :modal="false">
      <div v-if="accountLoading" style="padding: 40px; text-align: center; color: #909399;">
        <i class="el-icon-loading" style="font-size: 24px;"></i> 加载中...
      </div>
      <div v-else>
        <el-alert type="info" :closable="false" style="margin-bottom: 16px">
          登录态以 cookie 形式保存在数据库，不占用本地目录。每个账号每天限额 {{ dailyLimit }} 条。
        </el-alert>

        <el-table :data="accountList" size="small" border>
          <el-table-column prop="name" label="账号名称" min-width="150"></el-table-column>
          <el-table-column label="登录状态" min-width="100" align="center">
            <template slot-scope="scope">
              <el-tag v-if="scope.row.logged_in" type="success" size="small">已登录</el-tag>
              <el-tag v-else type="warning" size="small">未登录</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="Cookie 有效期" min-width="110" align="center">
            <template slot-scope="scope">
              <el-tag :type="cookieTag(scope.row.cookie_days).type" size="small">
                {{ cookieTag(scope.row.cookie_days).text }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="今日用量" min-width="100" align="center">
            <template slot-scope="scope">
              {{ scope.row.usage ? scope.row.usage.count : 0 }}/{{ dailyLimit }}
            </template>
          </el-table-column>
          <el-table-column label="启用" min-width="80" align="center">
            <template slot-scope="scope">
              <el-switch
                v-model="scope.row.enabled"
                @change="toggleAccount(scope.row)"
              ></el-switch>
            </template>
          </el-table-column>
          <el-table-column label="操作" min-width="200" align="center">
            <template slot-scope="scope">
              <el-button size="mini" type="primary" icon="el-icon-refresh" @click="handleCheckLogin(scope.row)">{{ scope.row.logged_in ? '刷新状态' : '登录/检查' }}</el-button>
              <el-button size="mini" type="info" icon="el-icon-open" @click="handleLaunch(scope.row)">打开豆包</el-button>
              <el-button size="mini" type="warning" icon="el-icon-edit" circle @click="renameAccount(scope.row)"></el-button>
              <el-button size="mini" type="danger" icon="el-icon-delete" circle @click="confirmDeleteAccount(scope.row)"></el-button>
            </template>
          </el-table-column>
        </el-table>

        <!-- 添加新账号 -->
        <div style="margin-top: 20px; padding-top: 16px; border-top: 1px solid rgba(255,255,255,0.1)">
          <div style="font-weight: 600; margin-bottom: 12px; color: var(--text-light)">添加新账号</div>
          <el-form :model="newAccount" label-width="90px" size="small">
            <el-form-item label="账号名称">
              <el-input v-model="newAccount.name" placeholder="如：豆包小号2" style="width: 260px"></el-input>
            </el-form-item>
            <el-button type="primary" size="small" icon="el-icon-plus" :loading="addingAccount" @click="handleAddAccount">添加账号</el-button>
          </el-form>
        </div>
      </div>
    </el-dialog>

    <!-- 手动补录视频弹窗：上传文件 / 粘贴直链 -->
    <el-dialog :title="`补录视频 · 分镜 ${manualShot ? manualShot.shot_no : ''}`" :visible.sync="showManualVideo" width="520px" :close-on-click-modal="false" :modal="false">
      <el-tabs v-model="manualTab">
        <el-tab-pane label="上传本地文件" name="file">
          <el-upload
            drag
            accept="video/mp4,video/mov,video/webm,video/x-matroska,.mp4,.mov,.webm,.mkv"
            :auto-upload="false"
            :show-file-list="true"
            :limit="1"
            :on-change="handleManualFileChange"
            :on-remove="() => { manualFile = null }"
          >
            <i class="el-icon-upload"></i>
            <div class="el-upload__text">拖拽视频到此处，或<em>点击选择文件</em></div>
            <div class="el-upload__tip" slot="tip">支持 MP4 / MOV / WebM / MKV</div>
          </el-upload>
          <div style="margin-top:16px;text-align:right">
            <el-button type="primary" size="small" :loading="manualUploading" :disabled="!manualFile" @click="submitManualUpload">上传并绑定</el-button>
          </div>
        </el-tab-pane>
        <el-tab-pane label="粘贴视频直链" name="url">
          <el-input
            v-model="manualUrl"
            type="textarea"
            :rows="3"
            placeholder="粘贴豆包视频地址（vdl.doubao.com 直链）"
          ></el-input>
          <div style="margin-top:16px;text-align:right">
            <el-button type="primary" size="small" :loading="manualUploading" :disabled="!manualUrl.trim()" @click="submitManualUrl">下载并绑定</el-button>
          </div>
        </el-tab-pane>
      </el-tabs>
    </el-dialog>

    <el-dialog :visible.sync="previewVisible" title="参考图预览" width="480px" :modal="false">
      <img v-if="previewImg" :src="previewImg" class="preview-img" />
    </el-dialog>
    </div>
  </div>
</template>

<script>
import { api } from '@/api'

export default {
  name: 'ShotPanel',
  props: {
    projectId: { type: String, required: true },
    videoSetId: { type: String, default: '' }
  },
  data() {
    return {
      project: null,
      loading: false,
      splitting: false,
      oneClickLoading: false,
      shots: [],
      characters: [],
      splitText: '',
      showBatchVideo: false,
      accountStatus: null,
      generatingBatch: false,
      showAccountManage: false,
      accountList: [],
      accountLoading: false,
      addingAccount: false,
      dailyLimit: 2,
      batchRunCount: 1,
      newAccount: { name: '' },
      showManualVideo: false,
      manualShot: null,
      manualTab: 'file',
      manualFile: null,
      manualUrl: '',
      manualUploading: false,
      promptEdit: {},
      previewVisible: false,
      previewImg: '',
      imageModelList: [],
      imageModelKey: ''
      manualUploading: false,
      promptEdit: {},
      previewVisible: false,
      previewImg: ''
    }
  },
  computed: {
    generatedCount() {
      return this.shots.filter(s => s.video_path).length
    },
    pendingCount() {
      return this.shots.filter(s => !s.video_path).length
    },
    imageModelItems() {
      return this.imageModelList.flatMap(m => {
        const models = m.models || (m.model ? [m.model] : [])
        return models.map(mid => ({
          key: m._id + '::' + mid,
          recordId: m._id,
          model: mid,
          label: m.name + '（' + mid + '）'
        }))
      })
    }
  },
  async mounted() {
    await this.loadProject()
    await Promise.all([this.loadShots(), this.loadCharacters(), this.loadImageModels()])
    // 连接SSE
    this.connectSSE()
  },
  beforeDestroy() {
    if (this.eventSource) this.eventSource.close()
  },
  methods: {
    async loadImageModels() {
      try {
        const r = await api.model.list()
        this.imageModelList = (r.data || []).filter(m => m.model_type === 'image')
        if (this.imageModelItems.length && !this.imageModelKey) {
          this.imageModelKey = this.imageModelItems[0].key
        }
      } catch (e) {
        console.error('加载文生图模型失败:', e)
      }
    },
    connectSSE() {
      const token = localStorage.getItem('token')
      // 走同源 /api 代理，避免写死 host 与跨域问题
      const url = `/api/video/events/${this.projectId}`
      this.eventSource = new EventSource(url)
      this.eventSource.onopen = () => {
        console.log('[SSE] 已连接:', url)
      }
      this.eventSource.onmessage = (e) => {
        try {
          const data = JSON.parse(e.data)
          console.log('[SSE] 收到事件:', data)
          // 更新分镜的生成状态
          const shot = this.shots.find(s => s.shot_no === data.shot_no)
          if (shot) {
            this.$set(shot, 'genStep', data.step)
            this.$set(shot, 'genProgress', data.progress)
            this.$set(shot, 'genMsg', data.msg)
          }
          // 完成后刷新列表
          if (data.step === 'done') {
            this.$message.success(`分镜 ${data.shot_no} 生成完成`)
            this.loadShots()
          }
        } catch (err) {
          console.error('[SSE] 消息解析失败:', err, e.data)
        }
      }
      this.eventSource.onerror = (err) => {
        console.error('[SSE] 连接异常/断开:', err)
      }
    },
    async exportToJianying() {
      try {
        const token = localStorage.getItem('token')
        const res = await fetch(`/api/video/export/jianying?project_id=${this.projectId}`, {
          headers: { 'Authorization': 'Bearer ' + token }
        })
        const data = await res.json()
        this.$message.success(data.msg || '已导出到剪映')
      } catch (e) {
        this.$message.error('导出失败: ' + e.message)
      }
    },
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
        const list = await api.shot.list(this.projectId, this.videoSetId)
        // 初始化生成状态字段，确保 Vue2 响应式可追踪（后补属性不会触发视图更新）
        this.shots = (list || []).map(s => ({
          ...s,
          genStep: '',
          genProgress: 0,
          genMsg: '',
          videoGenerating: false
        }))
      } catch (error) {
        console.error('加载分镜失败:', error)
      } finally {
        this.loading = false
      }
    },

    async loadCharacters() {
      try {
        this.characters = await api.character.list(this.projectId)
      } catch (error) {
        console.error('加载角色失败:', error)
      }
    },

    // 根据分镜的 character_name 匹配关联角色资产
    getCharacter(shot) {
      if (!shot || !shot.character_name) return null
      return this.characters.find(c => c.name === shot.character_name) || null
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
        await Promise.all([this.loadShots(), this.loadCharacters()])
      } catch (error) {
        console.error('拆分失败:', error)
      } finally {
        this.splitting = false
      }
    },

    // 一键提取：角色→道具→场景→拆分镜
    async handleOneClick() {
      if (!this.splitText.trim()) {
        this.$message.warning('请先粘贴小说段落')
        return
      }
      this.oneClickLoading = true
      try {
        this.$message.info('正在提取角色...')
        await api.character.extract({ project_id: this.projectId, novel_text: this.splitText })
        await this.loadCharacters()

        this.$message.info('正在提取道具...')
        await api.prop.extract({ project_id: this.projectId, novel_text: this.splitText })

        this.$message.info('正在提取场景...')
        await api.scene.extract({ project_id: this.projectId, novel_text: this.splitText })

        this.$message.info('正在拆分镜...')
        const res = await api.shot.split({
          project_id: this.projectId,
          novel_paragraph: this.splitText
        })
        await Promise.all([this.loadShots(), this.loadCharacters()])
        this.$message.success('一键提取完成！')
      } catch (error) {
        console.error('一键提取失败:', error)
        this.$message.error('部分步骤失败，请查看控制台')
      } finally {
        this.oneClickLoading = false
      }
    },

    async handleUpdate(shot) {
      try {
        await api.shot.update(shot.id, {
          text: shot.text,
          prompt: shot.prompt,
          video_prompt: shot.video_prompt,
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
        const sel = this.imageModelItems.find(i => i.key === this.imageModelKey)
        const payload = {
          shot_id: shot.id,
          prompt: shot.prompt,
          neg_prompt: shot.neg_prompt
        }
        if (sel) {
          payload.model_id = sel.recordId
          payload.model = sel.model
        }
        const res = await api.image.generate(payload)
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

      this.accountLoading = true
      this.showBatchVideo = true
      this.batchRunCount = this.pendingCount

      await this.$nextTick()
      try {
        const res = await api.video.getAccountStatus()
        this.accountStatus = res.data
      } catch (error) {
        console.error('加载账号状态失败:', error)
        this.$message.error('加载账号状态失败')
      } finally {
        this.accountLoading = false
      }
    },

    // ===== 账号管理 =====
    openAccountManage() {
      this.showBatchVideo = false
      this.showAccountManage = true
    },

    async loadAccountList() {
      this.accountLoading = true
      try {
        const res = await api.video.listAccounts()
        this.accountList = res.data.accounts
        this.dailyLimit = res.data.daily_limit || 2
      } catch (error) {
        console.error('加载账号列表失败:', error)
        this.$message.error('加载账号列表失败')
      } finally {
        this.accountLoading = false
      }
    },

    async handleAddAccount() {
      if (!this.newAccount.name.trim()) {
        this.$message.warning('请填写账号名称')
        return
      }
      this.addingAccount = true
      try {
        await api.video.addAccount({
          name: this.newAccount.name.trim()
        })
        this.$message.success('账号已创建，Chrome 已打开，请在浏览器中登录豆包')
        this.newAccount = { name: '' }
        await this.loadAccountList()
      } catch (error) {
        this.$message.error(error.response?.data?.detail || '添加失败')
      } finally {
        this.addingAccount = false
      }
    },

    cookieTag(days) {
      if (days === null || days === undefined) return { text: '未保存', type: 'info' }
      if (days <= 0) return { text: '已过期', type: 'danger' }
      if (days < 7) return { text: `剩 ${days} 天`, type: 'danger' }
      if (days < 14) return { text: `剩 ${days} 天`, type: 'warning' }
      return { text: `剩 ${days} 天`, type: 'success' }
    },
    async handleCheckLogin(row) {
      try {
        const res = await api.video.checkLogin(row.id)
        this.$message.success(res.message || '登录状态已更新')
        await this.loadAccountList()
      } catch (error) {
        this.$message.error(error.response?.data?.detail || '检查失败')
      }
    },

    async handleLaunch(row) {
      try {
        await api.video.launchDoubao(row.id)
        this.$message.success('已在 Chrome 打开豆包页面')
      } catch (error) {
        this.$message.error(error.response?.data?.detail || '打开失败')
      }
    },

    async toggleAccount(account) {
      try {
        await api.video.updateAccount(account.id, { enabled: account.enabled })
        this.$message.success(account.enabled ? `已启用 ${account.name}` : `已停用 ${account.name}`)
      } catch (error) {
        // 回滚
        account.enabled = !account.enabled
        this.$message.error('操作失败')
      }
    },

    confirmDeleteAccount(account) {
      this.$confirm(`确定删除账号 "${account.name}" 吗？`, '确认删除', {
        confirmButtonText: '删除',
        cancelButtonText: '取消',
        type: 'warning'
      }).then(async () => {
        try {
          await api.video.deleteAccount(account.id)
          this.$message.success('已删除')
          await this.loadAccountList()
        } catch (error) {
          this.$message.error(error.response?.data?.detail || '删除失败')
        }
      }).catch(() => {})
    },

    async renameAccount(account) {
      const { value } = await this.$prompt('请输入新账号名称', '重命名', {
        inputValue: account.name,
        confirmButtonText: '确定',
        cancelButtonText: '取消'
      })
      if (value && value.trim()) {
        try {
          await api.video.renameAccount(account.id, value.trim())
          this.$message.success('已重命名')
          await this.loadAccountList()
        } catch (error) {
          this.$message.error(error.response?.data?.detail || '重命名失败')
        }
      }
    },

    async handleBatchGenerate() {
      this.generatingBatch = true
      try {
        const res = await api.video.generateBatch(this.projectId, this.batchRunCount, true)

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
        await this.loadShots()

      } catch (error) {
        console.error('批量生成失败:', error)
        const msg = error.response?.data?.detail || error.message || '未知错误'
        this.$message.error('批量生成失败: ' + msg)
      } finally {
        this.generatingBatch = false
      }
    },

    async togglePrevFrame(shot) {
      this.$set(shot, 'use_prev_frame', !shot.use_prev_frame)
      await this.$http.put(`/api/project/${this.projectId}/shot/${shot._id}`, { use_prev_frame: shot.use_prev_frame })
    },

    async handleRegenerateVideo(shot) {
      this.$confirm('确定为该分镜生成视频吗？将打开豆包自动化浏览器。', '提示', {
        confirmButtonText: '确定',
        cancelButtonText: '取消',
        type: 'info'
      }).then(async () => {
        shot.videoGenerating = true
        try {
          const res = await api.video.generateSingle(shot.id, null)
          this.$message.success(res.message || '视频生成成功')
          await this.loadShots()
        } catch (error) {
          console.error('生成视频失败:', error)
          const msg = error.response?.data?.detail || error.message || '未知错误'
          this.$message.error('生成视频失败: ' + msg)
        } finally {
          shot.videoGenerating = false
        }
      }).catch(() => {})
    },

    openManualVideo(shot) {
      this.manualShot = shot
      this.manualTab = 'file'
      this.manualFile = null
      this.manualUrl = ''
      this.showManualVideo = true
    },
    handleManualFileChange(file) {
      this.manualFile = file.raw || null
    },
    async submitManualUpload() {
      if (!this.manualShot || !this.manualFile) return
      this.manualUploading = true
      try {
        const res = await api.video.uploadShotVideo(this.manualShot.id, this.manualFile)
        this.$message.success(res.message || '视频已上传')
        this.showManualVideo = false
        await this.loadShots()
      } catch (error) {
        const msg = error.response?.data?.detail || error.message || '上传失败'
        this.$message.error(msg)
      } finally {
        this.manualUploading = false
      }
    },
    async submitManualUrl() {
      if (!this.manualShot || !this.manualUrl.trim()) return
      this.manualUploading = true
      try {
        const res = await api.video.fetchShotVideoByUrl(this.manualShot.id, this.manualUrl.trim())
        this.$message.success(res.message || '视频已下载')
        this.showManualVideo = false
        await this.loadShots()
      } catch (error) {
        const msg = error.response?.data?.detail || error.message || '下载失败'
        this.$message.error(msg)
      } finally {
        this.manualUploading = false
      }
    },

    isEditingPrompt(shot) {
      return !!this.promptEdit[shot.id]
    },
    toggleEditPrompt(shot) {
      this.$set(this.promptEdit, shot.id, !this.promptEdit[shot.id])
    },
    onPromptChange(shot) {
      this.handleUpdate(shot)
      this.$set(this.promptEdit, shot.id, false)
    },
    refAssets(shot) {
      return (shot.assets || []).filter(a => a.type !== '分镜参考')
    },
    parsePrompt(shot) {
      const text = shot.video_prompt || ''
      const refs = this.refAssets(shot)
      const segs = []
      const re = /【@图片(\d+)】/g
      let last = 0, m
      while ((m = re.exec(text))) {
        if (m.index > last) segs.push({ type: 'text', text: text.slice(last, m.index) })
        const num = parseInt(m[1], 10)
        const asset = refs[num - 1]
        segs.push({ type: 'ref', num, img: asset && asset.img ? asset.img : null })
        last = re.lastIndex
      }
      if (last < text.length) segs.push({ type: 'text', text: text.slice(last) })
      return segs
    },
    previewRef(shot, num) {
      const asset = this.refAssets(shot)[num - 1]
      if (!asset || !asset.img) {
        this.$message.info('该参考图尚未生成')
        return
      }
      this.previewImg = this.getStaticUrl(asset.img)
      this.previewVisible = true
    },

    getStaticUrl(path) {
      return api.staticUrl(path)
    }
  }
}
</script>

<style scoped>
.video-set-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
}
.video-set-bar .el-tabs {
  flex: 1;
}
/* 拆分区 */
.control-card {
  margin-bottom: 24px;
  background: rgba(30, 41, 59, 0.6);
  backdrop-filter: blur(20px);
  border-radius: var(--radius-md);
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4);
  border: 1px solid rgba(255, 255, 255, 0.1);
}

.control-card >>> .el-card__header {
  background: rgba(255, 255, 255, 0.05);
  border-bottom: 1px solid rgba(255, 255, 255, 0.1);
  font-weight: 600;
  color: var(--text-light);
}

.control-card >>> .el-card__body {
  padding: 20px 24px;
}

.control-title {
  font-size: 16px;
}

.control-sub {
  float: right;
  font-size: 13px;
  color: var(--text-tertiary);
  font-weight: 400;
}

.split-row {
  display: flex;
  gap: 16px;
  align-items: stretch;
}

.split-row .el-textarea {
  flex: 1;
}

.split-btn {
  min-width: 140px;
  align-self: stretch;
  height: auto;
}

/* 工具栏 */
.shot-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin: 0 0 18px;
  padding: 14px 20px;
  background: rgba(30, 41, 59, 0.5);
  backdrop-filter: blur(20px);
  border-radius: var(--radius-md);
  border: 1px solid rgba(255, 255, 255, 0.1);
}

.toolbar-title {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 16px;
  font-weight: 600;
  color: var(--text-light);
}

.toolbar-actions {
  display: flex;
  gap: 10px;
}

/* 分镜卡片列表 */
.shot-list {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.shot-card {
  background: rgba(30, 41, 59, 0.6);
  backdrop-filter: blur(20px);
  border-radius: var(--radius-md);
  border: 1px solid rgba(255, 255, 255, 0.1);
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.35);
  overflow: hidden;
  transition: box-shadow 0.2s, border-color 0.2s;
}

.shot-card:hover {
  border-color: rgba(129, 140, 248, 0.4);
  box-shadow: 0 12px 40px rgba(0, 0, 0, 0.45);
}

/* 卡片头部 */
.shot-card-head {
  display: flex;
  align-items: center;
  padding: 10px 16px;
  background: rgba(255, 255, 255, 0.04);
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  gap: 14px;
}

.shot-badge {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
}

.shot-no {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 30px;
  height: 30px;
  padding: 0 8px;
  border-radius: 8px;
  font-size: 14px;
  font-weight: 700;
  color: #fff;
  background: var(--primary-gradient);
  box-shadow: 0 4px 12px rgba(102, 126, 234, 0.4);
}

.shot-duration {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: var(--text-secondary);
}

.shot-params {
  display: flex;
  gap: 8px;
  flex: 1;
  flex-wrap: wrap;
}

.param-select {
  width: 130px;
}

.shot-head-actions {
  display: flex;
  gap: 8px;
  flex-shrink: 0;
}

/* 卡片主体 */
.shot-card-body {
  display: flex;
  padding: 14px 16px;
  gap: 16px;
  align-items: flex-start;
}

/* 左：画面参考图 */
.shot-visual {
  flex-shrink: 0;
  width: 260px;
}

.shot-img-wrap {
  position: relative;
  border-radius: var(--radius-md);
  overflow: hidden;
  aspect-ratio: 16 / 9;
  background: rgba(15, 23, 42, 0.6);
  border: 1px solid rgba(255, 255, 255, 0.1);
}

.shot-img {
  width: 100%;
  height: 100%;
  display: block;
}

/* 右：视频列 */
.shot-video-col {
  flex-shrink: 0;
  width: 260px;
}

.shot-video-wrap {
  position: relative;
  width: 100%;
  border-radius: 8px;
  overflow: hidden;
}

.shot-video {
  width: 100%;
  display: block;
  background: #000;
}

.shot-video-empty {
  width: 100%;
  aspect-ratio: 16 / 9;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  border-radius: var(--radius-md);
  border: 1px dashed rgba(255, 255, 255, 0.15);
  background: rgba(15, 23, 42, 0.4);
  color: var(--text-tertiary);
  font-size: 12px;
}

.shot-video-empty .el-icon-video-camera {
  font-size: 24px;
}

.shot-assets {
  margin-top: 8px;
}

.assets-label {
  font-size: 11px;
  color: #909399;
  margin-bottom: 4px;
}

.assets-row {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.asset-thumb {
  text-align: center;
}

.asset-thumb img {
  width: 48px;
  height: 48px;
  object-fit: cover;
  border-radius: 4px;
  display: block;
  border: 1px solid #444;
}

.asset-thumb span {
  font-size: 10px;
  color: #909399;
}

.img-hint {
  position: absolute;
  bottom: 8px;
  left: 8px;
  font-size: 12px;
  color: var(--text-light);
  background: rgba(15, 23, 42, 0.7);
  backdrop-filter: blur(4px);
  padding: 2px 10px;
  border-radius: 6px;
}

.shot-img-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  aspect-ratio: 16 / 9;
  border-radius: var(--radius-md);
  border: 1px dashed rgba(255, 255, 255, 0.2);
  background: rgba(15, 23, 42, 0.4);
  color: var(--text-tertiary);
  cursor: pointer;
  transition: border-color 0.2s, background 0.2s;
}

.shot-img-empty:hover {
  border-color: rgba(129, 140, 248, 0.5);
  background: rgba(15, 23, 42, 0.6);
}

.shot-img-empty .el-icon-picture-outline,
.empty-icon-big {
  font-size: 40px;
}

.empty-tip {
  font-size: 13px;
}

/* 中：台词 + 提示词 + 资产 */
.shot-info {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 0;
}

.prompt-input >>> .el-textarea__inner {
  background: rgba(15, 23, 42, 0.6);
  border-color: rgba(99, 102, 241, 0.3);
  font-size: 12px;
  line-height: 1.5;
  color: #e0e7ff;
}

.shot-text-input >>> .el-textarea__inner {
  max-height: 72px;
  overflow-y: auto;
  font-size: 12px;
  line-height: 1.5;
  color: #e0e7ff;
}

.prompt-block {
  position: relative;
}

.prompt-view {
  background: rgba(15, 23, 42, 0.6);
  border: 1px solid rgba(99, 102, 241, 0.3);
  border-radius: 4px;
  padding: 8px 10px;
  font-size: 12px;
  line-height: 1.7;
  color: #e0e7ff;
  white-space: pre-wrap;
  word-break: break-word;
  min-height: 48px;
  max-height: 120px;
  overflow-y: auto;
}

.ref-chip {
  display: inline-flex;
  align-items: center;
  padding: 0 5px;
  margin: 0 1px;
  border-radius: 4px;
  background: rgba(34, 211, 238, 0.18);
  border: 1px solid rgba(34, 211, 238, 0.5);
  color: #67e8f9;
  cursor: pointer;
  font-size: 11px;
}

.ref-chip:hover {
  background: rgba(34, 211, 238, 0.32);
}

.ref-chip.missing {
  background: rgba(148, 163, 184, 0.12);
  border-color: rgba(148, 163, 184, 0.35);
  color: #94a3b8;
  cursor: default;
}

.prompt-edit-btn {
  position: absolute;
  top: 0;
  right: 0;
  padding: 2px 6px;
  font-size: 11px;
}

.preview-img {
  width: 100%;
  border-radius: 6px;
  display: block;
}

.prompt-block {
  position: relative;
}

.prompt-view {
  background: rgba(15, 23, 42, 0.6);
  border: 1px solid rgba(99, 102, 241, 0.3);
  border-radius: 4px;
  padding: 8px 10px;
  font-size: 12px;
  line-height: 1.7;
  color: #e0e7ff;
  white-space: pre-wrap;
  word-break: break-word;
  min-height: 48px;
}

.ref-chip {
  display: inline-flex;
  align-items: center;
  padding: 0 5px;
  margin: 0 1px;
  border-radius: 4px;
  background: rgba(34, 211, 238, 0.18);
  border: 1px solid rgba(34, 211, 238, 0.5);
  color: #67e8f9;
  cursor: pointer;
  font-size: 11px;
}

.ref-chip:hover {
  background: rgba(34, 211, 238, 0.32);
}

.ref-chip.missing {
  background: rgba(148, 163, 184, 0.12);
  border-color: rgba(148, 163, 184, 0.35);
  color: #94a3b8;
  cursor: default;
}

.prompt-edit-btn {
  position: absolute;
  top: 0;
  right: 0;
  padding: 2px 6px;
  font-size: 11px;
}

.preview-img {
  width: 100%;
  border-radius: 6px;
  display: block;
}

.asset-tags-compact {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.asset-tag {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 2px 8px 2px 3px;
  border-radius: 999px;
  background: rgba(99, 102, 241, 0.12);
  border: 1px solid rgba(99, 102, 241, 0.25);
  font-size: 11px;
  color: #c7d2fe;
}

.asset-tag .asset-role {
  font-style: normal;
  font-size: 10px;
  opacity: 0.7;
  padding: 0 4px;
  border-left: 1px solid rgba(199, 210, 254, 0.3);
}

.asset-tag .asset-thumb {
  width: 20px;
  height: 20px;
  border-radius: 50%;
  cursor: pointer;
  flex-shrink: 0;
}

.asset-tag .el-icon-picture-outline {
  font-size: 16px;
  margin-left: 4px;
}

.info-field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.field-label {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 600;
  color: var(--text-secondary);
}

.label-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--primary);
  flex-shrink: 0;
}

.info-row {
  display: flex;
  gap: 16px;
}

/* 豆包自动化提示词 - 核心字段，醒目突出 */
.prompt-field {
  padding: 12px 14px;
  background: rgba(99, 102, 241, 0.08);
  border: 1px solid rgba(99, 102, 241, 0.25);
  border-radius: var(--radius);
}

.prompt-label {
  font-size: 14px;
  color: #a5b4fc;
  font-weight: 700;
}

.prompt-dot {
  background: #818cf8;
  box-shadow: 0 0 6px rgba(129, 140, 248, 0.6);
}

.prompt-tag {
  font-size: 11px;
  font-weight: 400;
  color: var(--text-tertiary);
  background: rgba(99, 102, 241, 0.15);
  padding: 1px 8px;
  border-radius: 4px;
  margin-left: 4px;
}

.prompt-field >>> .el-textarea__inner {
  background: rgba(15, 23, 42, 0.7);
  border-color: rgba(99, 102, 241, 0.3);
  font-size: 13px;
  line-height: 1.6;
  color: #e0e7ff;
}

.prompt-field >>> .el-textarea__inner:focus {
  border-color: #818cf8;
  box-shadow: 0 0 0 2px rgba(129, 140, 248, 0.15);
}

.dur-field >>> .el-input-number {
  width: 200px;
}

/* 关联资产 */
.asset-block {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 10px 14px;
  background: rgba(15, 23, 42, 0.4);
  border-radius: var(--radius);
  border: 1px solid rgba(255, 255, 255, 0.08);
}

.asset-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.asset-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 6px 12px 6px 6px;
  background: rgba(129, 140, 248, 0.12);
  border: 1px solid rgba(129, 140, 248, 0.25);
  border-radius: 10px;
}

.asset-avatar {
  width: 44px;
  height: 44px;
  border-radius: 8px;
  overflow: hidden;
  background: rgba(15, 23, 42, 0.6);
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-tertiary);
  font-size: 22px;
  flex-shrink: 0;
}

.asset-avatar img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.asset-name {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-light);
}

.asset-voice {
  font-size: 12px;
  color: var(--text-secondary);
  margin-top: 2px;
}

.asset-type {
  font-size: 11px;
  color: #909399;
  margin-top: 2px;
}

/* 音频 */
.audio-field >>> .shot-audio {
  width: 100%;
  height: 32px;
}

.audio-field >>> .el-button {
  align-self: flex-start;
}

/* 空状态 */
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 60px 0;
  color: var(--text-tertiary);
}

.empty-icon {
  font-size: 56px;
  margin-bottom: 16px;
  color: rgba(255, 255, 255, 0.15);
}

.empty-state p {
  font-size: 14px;
}

/* 输入框暗色适配 */
.shot-card >>> .el-textarea__inner,
.shot-card >>> .el-input__inner {
  background: rgba(15, 23, 42, 0.6);
  border-color: rgba(255, 255, 255, 0.12);
  color: var(--text-light);
}

.shot-card >>> .el-textarea__inner:focus,
.shot-card >>> .el-input__inner:focus {
  border-color: var(--primary);
}

/* 对话框暗色 */
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

>>> .el-alert {
  border-radius: var(--radius);
  background: rgba(15, 23, 42, 0.7) !important;
  border: 1px solid rgba(255, 255, 255, 0.12) !important;
  color: var(--text-secondary) !important;
}

>>> .el-alert__title {
  color: var(--text-light) !important;
}

/* 弹窗内表格暗色 */
>>> .el-table {
  background: transparent;
  color: var(--text-light);
}

>>> .el-table th {
  background: rgba(15, 23, 42, 0.8) !important;
  color: var(--text-secondary) !important;
  border-bottom: 1px solid rgba(255, 255, 255, 0.12) !important;
}

>>> .el-table tr {
  background: transparent !important;
}

>>> .el-table td {
  background: transparent !important;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08) !important;
  color: var(--text-light);
}

>>> .el-table--border,
>>> .el-table--group {
  border-color: rgba(255, 255, 255, 0.12) !important;
}

>>> .el-table--border td,
>>> .el-table--border th {
  border-right: 1px solid rgba(255, 255, 255, 0.12) !important;
}

/* 弹窗内表单暗色 */
>>> .el-form-item__label {
  color: var(--text-secondary);
}

>>> .el-input__inner {
  background: rgba(15, 23, 42, 0.6);
  border-color: rgba(255, 255, 255, 0.12);
  color: var(--text-light);
}

/* 响应式：窄屏时三列改上下 */
@media (max-width: 900px) {
  .shot-card-body {
    flex-direction: column;
  }
  .shot-visual,
  .shot-video-col {
    width: 300px;
    max-width: 100%;
  }
}
</style>

<!-- 非scoped：弹窗append-to-body后scoped样式失效，必须用全局 -->
<style>
.el-dialog .el-alert {
  background: rgba(15, 23, 42, 0.8) !important;
  border: 1px solid rgba(255, 255, 255, 0.12) !important;
  color: #cbd5e1 !important;
}
.el-dialog .el-alert__title {
  color: #f1f5f9 !important;
}
.el-dialog .el-table {
  background: transparent !important;
  color: #f1f5f9 !important;
}
.el-dialog .el-table th {
  background: rgba(15, 23, 42, 0.9) !important;
  color: #94a3b8 !important;
  border-bottom: 1px solid rgba(255, 255, 255, 0.12) !important;
}
.el-dialog .el-table tr,
.el-dialog .el-table td {
  background: transparent !important;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08) !important;
  color: #f1f5f9 !important;
}
.el-dialog .el-table--border,
.el-dialog .el-table--group {
  border-color: rgba(255, 255, 255, 0.12) !important;
}
.el-dialog .el-table--border td,
.el-dialog .el-table--border th {
  border-right: 1px solid rgba(255, 255, 255, 0.12) !important;
}
.el-dialog .el-form-item__label {
  color: #94a3b8 !important;
}
.el-dialog .el-input__inner,
.el-dialog .el-textarea__inner {
  background: rgba(15, 23, 42, 0.6) !important;
  border-color: rgba(255, 255, 255, 0.12) !important;
  color: #f1f5f9 !important;
}
.el-dialog .el-switch__label {
  color: #94a3b8 !important;
}
</style>
