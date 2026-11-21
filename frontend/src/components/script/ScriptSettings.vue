<template>
  <section class="section">
    <h2 class="section-title">转剧本设置</h2>
    <FormField label="模型">
      <ModelSelect :value="value.model" :groups="modelGroups" @input="v => set('model', v)" />
    </FormField>
    <FormField v-if="prompts.length" label="提示词">
      <PromptSelect :value="value.prompt" :prompts="prompts" @input="v => set('prompt', v)" />
    </FormField>
    <FormField label="叙事人称" hint="旁白用哪种人称讲；心声始终是角色自己的“我”。">
      <el-select :value="person" :disabled="saving" @change="v => save({ script_person: v })">
        <el-option v-for="p in persons" :key="p.value" :label="p.label" :value="p.value"></el-option>
      </el-select>
    </FormField>
    <FormField label="目标时长（秒，可空）" :hint="targetHint">
      <el-input-number
        :value="targetSeconds"
        :min="0"
        :max="3600"
        :step="10"
        :disabled="saving"
        controls-position="right"
        placeholder="不限定"
        @change="v => save({ script_target_seconds: v || 0 })"
      />
    </FormField>
    <p class="note">叙事人称和目标时长存在作品里，下次转剧本沿用。</p>
  </section>
</template>

<script>
/**
 * 剧本页右侧“转剧本设置”：模型、提示词（v-model: { model, prompt }，只在本页用），
 * 叙事人称、目标时长（存作品：project.script_person / script_target_seconds，emit('save-project', fields) 由页面保存）。
 * 目标时长为空 = 台词约为原文三成；有目标时长时按语速口径换算字数，提示里给出估算。
 * 语速（字/秒）与台词余量来自接口 pacing（backend/core/pacing.py 唯一来源），前端不另写常数，避免与后端剧本篇幅预算口径分裂。
 */
import ModelSelect from '@/components/novel/ModelSelect.vue'
import PromptSelect from '@/components/novel/PromptSelect.vue'
import { loadPacing, loadVideoModels, findModel } from '@/components/project/videoModels'
import { SCRIPT_PERSON_OPTIONS, DEFAULT_SCRIPT_PERSON } from './scene'

export default {
  name: 'ScriptSettings',
  components: { ModelSelect, PromptSelect },
  props: {
    value: { type: Object, required: true },
    modelGroups: { type: Array, default: () => [] },
    prompts: { type: Array, default: () => [] },
    project: { type: Object, default: null },
    saving: Boolean
  },
  data() {
    return { persons: SCRIPT_PERSON_OPTIONS, pacing: null, segmentSeconds: 15 }
  },
  computed: {
    person() { return (this.project && this.project.script_person) || DEFAULT_SCRIPT_PERSON },
    targetSeconds() {
      const v = this.project && this.project.script_target_seconds
      return v ? Number(v) : undefined
    },
    targetHint() {
      if (!this.targetSeconds) return '不填时台词约为原文的三成；想控制成片长度就填，比如 120 秒约 10 个视频段。'
      if (!this.pacing) return '按目标时长控制台词总字数（语速口径加载中）。'
      // 每段台词时长 = 段时长 - 动作余量，与后端 video_models.segment_params 的 content_high 一致
      // 每段只装 (段时长 - 余量) 秒台词：台词字数按这部分时长算，段数按段时长算（与后端 pacing.speech_seconds_for_target 一致）
      const perSegment = Math.max(this.segmentSeconds - (this.pacing.speech_margin_seconds || 0), 1)
      const chars = Math.floor(this.targetSeconds * perSegment / this.segmentSeconds * this.pacing.chars_per_second)
      const segs = Math.max(1, Math.round(this.targetSeconds / this.segmentSeconds))
      return `台词合计不超过约 ${chars} 字，约 ${segs} 个视频段。`
    }
  },
  created() {
    loadPacing().then(p => { this.pacing = p }).catch(() => {})
    loadVideoModels().then(models => {
      const m = findModel(models, this.project && this.project.video_model)
      if (m && m.max_duration) this.segmentSeconds = m.max_duration
    }).catch(() => {})
  },
  methods: {
    set(key, v) { this.$emit('input', { ...this.value, [key]: v }) },
    save(fields) { this.$emit('save-project', fields) }
  }
}
</script>
