<template>
  <details class="fold">
    <summary>润色</summary>
    <div class="fold__body">
      <p class="note">把正文改写成更适合漫剧的文本。只生成结果，确认后才会替换正文。</p>
      <FormField label="人称">
        <el-radio-group v-model="person" size="small">
          <el-radio-button v-for="p in persons" :key="p.value" :label="p.value">{{ p.label }}</el-radio-button>
        </el-radio-group>
      </FormField>
      <FormField label="模型">
        <ModelSelect v-model="modelKey" :groups="modelGroups" />
      </FormField>
      <FormField label="提示词">
        <PromptSelect v-model="promptId" :prompts="prompts" />
      </FormField>
      <div class="inline-actions">
        <BaseButton :loading="running" @click="run">{{ running ? '正在润色…' : '润色全文' }}</BaseButton>
      </div>
    </div>
  </details>
</template>

<script>
/** 调后端 POST /api/novel/polish，结果 emit('result', { text, sourceLength })，由父组件弹确认框。 */
import { api } from '@/api'
import { toastError, toastWarning } from '@/utils/notify'
import ModelSelect from './ModelSelect.vue'
import PromptSelect from './PromptSelect.vue'
import { PERSON_OPTIONS, parseModelKey } from './options'

export default {
  name: 'PolishPanel',
  components: { ModelSelect, PromptSelect },
  props: {
    projectId: { type: String, required: true },
    text: { type: String, default: '' },
    modelGroups: { type: Array, default: () => [] },
    defaultModel: { type: String, default: '' },
    prompts: { type: Array, default: () => [] }
  },
  data() {
    return { persons: PERSON_OPTIONS, person: '', modelKey: this.defaultModel, promptId: '', running: false }
  },
  watch: {
    defaultModel(v) { if (!this.modelKey) this.modelKey = v }
  },
  methods: {
    async run() {
      if (!this.text.trim()) { toastWarning('正文是空的，先贴入小说'); return }
      this.running = true
      try {
        const res = await api.novel.polish({
          project_id: this.projectId,
          text: this.text,
          ...parseModelKey(this.modelKey),
          prompt_id: this.promptId,
          person: this.person
        })
        const data = (res && res.data) || {}
        if (!data.text) throw new Error('模型没有返回内容')
        this.$emit('result', { text: data.text, sourceLength: data.source_length || this.text.length })
      } catch (e) {
        toastError(e, '润色失败')
      } finally {
        this.running = false
      }
    }
  }
}
</script>
