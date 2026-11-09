<template>
  <details class="fold">
    <summary>AI 写一篇小说</summary>
    <div class="fold__body">
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
      <FormField label="提示词模板">
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

export default {
  name: 'NovelWriter',
  components: { PromptSelect },
  props: {
    projectId: { type: String, required: true },
    prompts: { type: Array, default: () => [] },
    /** 作品当前题材（id / 名称 / 题材键都可） */
    defaultGenre: { type: String, default: '' }
  },
  data() {
    return {
      genres: [],
      running: false,
      form: { genre: '', outline: '', protagonist: '', prompt_id: '', target_words: 5000 }
    }
  },
  watch: {
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
      // EventSource 不能带请求头，token 走查询参数
      this.source = new EventSource(api.novel.generateStreamUrl({
        project_id: this.projectId,
        genre: genre.genre,
        style: genre.name,
        outline: this.form.outline,
        protagonist: this.form.protagonist,
        target_words: this.form.target_words,
        prompt_id: this.form.prompt_id,
        token: localStorage.getItem('token') || ''
      }))
      this.source.onmessage = e => {
        let data
        try { data = JSON.parse(e.data) } catch (err) { toastError(err, '生成内容解析失败'); this.finish(); return }
        if (data.type === 'chunk') this.$emit('chunk', data.content)
        else if (data.type === 'done') { toastSuccess('小说生成完成'); this.finish() }
        else if (data.type === 'error') { toastError(new Error(data.message), '生成失败'); this.finish() }
      }
      this.source.onerror = () => {
        toastError(null, '连接中断，请检查网络或模型配置')
        this.finish()
      }
    },
    stop() { this.finish() },
    finish() {
      this.close()
      this.running = false
      this.$emit('finish')
    },
    close() {
      if (this.source) { this.source.close(); this.source = null }
    }
  }
}
</script>
