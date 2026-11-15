<template>
  <details class="fold" open>
    <summary>AI 写一篇小说</summary>
    <div class="fold__body">
      <FormField label="模型">
        <ModelSelect v-model="modelKey" :groups="modelGroups" />
      </FormField>
      <FormField label="题材">
        <el-select v-model="form.genre">
          <el-option v-for="g in genres" :key="g.id" :label="g.name" :value="g.id"></el-option>
        </el-select>
      </FormField>
      <FormField label="故事梗概" required>
        <el-input v-model="form.outline" type="textarea" :autosize="{ minRows: 2, maxRows: 6 }" placeholder="简要描述故事情节" />
      </FormField>
      <FormField label="主角设定" required>
        <el-input v-model="form.protagonist" type="textarea" :autosize="{ minRows: 2, maxRows: 6 }" placeholder="主角背景、性格等" />
      </FormField>
      <FormField v-if="prompts.length" label="提示词模板">
        <PromptSelect v-model="form.prompt_id" :prompts="prompts" placeholder="默认提示词" />
      </FormField>
      <FormField label="目标字数">
        <el-input-number v-model="form.target_words" :min="1000" :max="50000" :step="1000" controls-position="right" />
      </FormField>
      <div class="inline-actions">
        <BaseButton :loading="running" @click="start">{{ running ? '正在写…' : '开始生成' }}</BaseButton>
        <BaseButton v-if="running" variant="text" @click="stop">停止</BaseButton>
      </div>
      <p class="note">生成的内容会替换左侧正文，写完后记得保存。</p>
    </div>
  </details>
</template>

<script>
/**
 * AI 写小说（SSE 流式）。emit：start（清空正文）→ chunk(text) 多次 → finish。
 * 生成结果由父组件放进正文编辑框。题材下拉来自风格库（components/project/styleLibrary.js），默认作品当前题材。
 */
import { api } from '@/api'
import { toastError, toastSuccess, toastWarning } from '@/utils/notify'
import { loadStyleLibrary } from '@/components/project/styleLoader'
import { findGenre } from '@/components/project/styleLibrary'
import PromptSelect from './PromptSelect.vue'
import ModelSelect from './ModelSelect.vue'
import { parseModelKey } from './options'

export default {
  name: 'NovelWriter',
  components: { PromptSelect, ModelSelect },
  props: {
    projectId: { type: String, required: true },
    setId: { type: String, default: '' },
    prompts: { type: Array, default: () => [] },
    modelGroups: { type: Array, default: () => [] },
    defaultModel: { type: String, default: '' },
    /** 作品当前题材（id / 名称 / 题材键都可） */
    defaultGenre: { type: String, default: '' }
  },
  data() {
    return {
      genres: [],
      running: false,
      modelKey: this.defaultModel,
      form: { genre: '', outline: '', protagonist: '', prompt_id: '', target_words: 5000 }
    }
  },
  watch: {
    defaultModel(v) { if (!this.modelKey) this.modelKey = v },
    defaultGenre() { this.pickDefaultGenre() },
    prompts: {
      immediate: true,
      handler(list) {
        const def = list.find(p => p.is_default)
        if (def && !this.form.prompt_id) this.form.prompt_id = def._id
      }
    }
  },
  created() {
    loadStyleLibrary().then(lib => { this.genres = lib.genres; this.pickDefaultGenre() }, e => toastError(e, '风格库加载失败'))
  },
  beforeDestroy() {
    this.close()
  },
  methods: {
    pickDefaultGenre() {
      const lib = { genres: this.genres }
      const g = findGenre(lib, this.defaultGenre) || this.genres[0]
      if (g) this.form.genre = g.id
    },
    start() {
      if (!this.form.outline.trim() || !this.form.protagonist.trim()) {
        toastWarning('请填写故事梗概和主角设定')
        return
      }
      const genre = this.genres.find(g => g.id === this.form.genre) || this.genres[0] || { genre: '', name: '' }
      this.running = true
      this.$emit('start')
      // fetch 流：用户 JWT、本地令牌走请求头；stop() / 离开页面用 AbortController 取消
      const ctrl = new AbortController()
      this.source = ctrl
      let ended = false
      const end = () => { ended = true; this.finish() }
      api.novel.generateStream({
        project_id: this.projectId,
        video_set_id: this.setId || '',
        genre: genre.genre,
        style: genre.name,
        outline: this.form.outline,
        protagonist: this.form.protagonist,
        target_words: this.form.target_words,
        prompt_id: this.form.prompt_id,
        ...parseModelKey(this.modelKey)
      }, {
        signal: ctrl.signal,
        onMessage: raw => {
          let data
          try { data = JSON.parse(raw) } catch (err) { toastError(err, '生成内容解析失败'); end(); return false }
          if (data.type === 'chunk') this.$emit('chunk', data.content)
          else if (data.type === 'done') { toastSuccess('小说生成完成'); end(); return false } else if (data.type === 'error') { toastError(new Error(data.message), '生成失败'); end(); return false }
        },
        // 连接失败、断线、服务端未发完成事件就关流，都按“连接中断”处理（同原 EventSource.onerror）
        onError: () => { if (!ended) { toastError(null, '连接中断，请检查网络或模型配置'); end() } },
        onClose: () => { if (!ended) { toastError(null, '连接中断，请检查网络或模型配置'); end() } }
      })
    },
    stop() { this.finish() },
    finish() {
      this.close()
      this.running = false
      this.$emit('finish')
    },
    close() {
      if (this.source) { this.source.abort(); this.source = null }
    }
  }
}
</script>
