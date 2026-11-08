<template>
  <section class="shot-detail" :aria-label="`镜头 ${shot.shot_no} 详情`">
    <div class="section__head">
      <h2 class="shot-detail__title">镜头 {{ shot.shot_no }}</h2>
      <StatusText class="small" :status="st.status" :n="st.n" />
    </div>

    <MediaFrame :key="media" :src="media" :tone="shot.shot_no" ratio="16 / 9" :controls="!!shot.video_path" :label="progressText" />

    <div class="inline-actions">
      <BaseButton :loading="videoBusy" @click="$emit('generate-video', shot)">{{ shot.video_path ? '重新生成视频' : '生成视频' }}</BaseButton>
      <BaseButton variant="text" @click="$emit('manual-video', shot)">补录视频</BaseButton>
      <BaseButton variant="text" :loading="imageBusy" @click="$emit('generate-image', shot)">{{ shot.img_path ? '重新生成画面' : '生成画面' }}</BaseButton>
      <BaseButton variant="text" @click="$emit('delete', shot)">删除镜头</BaseButton>
    </div>

    <FormField label="台词">
      <el-input v-model="draft.text" type="textarea" :autosize="{ minRows: 2, maxRows: 6 }" placeholder="台词 / 旁白" @change="save('text')" />
    </FormField>
    <FormField label="说话人">
      <el-select v-model="draft.character_name" filterable allow-create @change="save('character_name')">
        <el-option v-for="name in speakers" :key="name" :label="name" :value="name"></el-option>
      </el-select>
    </FormField>
    <div class="field-group">
      <span class="field-label">用到的资产</span>
      <ShotAssets :assets="shot.assets || []" />
    </div>

    <details class="fold fold--plain">
      <summary>提示词与生成参数</summary>
      <div class="fold__body">
        <FormField label="视频提示词">
          <el-input v-model="draft.video_prompt" type="textarea" :autosize="{ minRows: 3, maxRows: 10 }" @change="save('video_prompt')" />
        </FormField>
        <FormField label="画面提示词" hint="生成画面（参考图）用">
          <el-input v-model="draft.prompt" type="textarea" :autosize="{ minRows: 3, maxRows: 10 }" placeholder="豆包自动化提示词" @change="save('prompt')" />
        </FormField>
        <div class="form-row">
          <FormField label="时长（秒）">
            <el-input-number v-model="draft.duration" :min="0.5" :max="30" :step="0.5" controls-position="right" @change="save('duration')" />
          </FormField>
          <FormField label="模型" hint="暂未接入，按默认生成">
            <el-select value="" disabled placeholder="Seedance 2.0 Fast" />
          </FormField>
          <FormField label="比例" hint="暂未接入，按默认生成">
            <el-select value="" disabled placeholder="16:9 横屏" />
          </FormField>
        </div>
        <el-checkbox disabled>用上一镜尾帧作关键帧（需要后端支持，暂不可用）</el-checkbox>
      </div>
    </details>
  </section>
</template>

<script>
/**
 * 单个镜头的详情：播放/预览、生成与补录、台词与说话人、用到的资产、提示词。
 * 字段改完（失焦/选择）即 emit('save', shot, { 字段: 值 })，由页面提交。
 */
import { api } from '@/api'
import { shotStatus, NARRATOR } from './status'
import ShotAssets from './ShotAssets.vue'

const FIELDS = ['text', 'character_name', 'video_prompt', 'prompt', 'duration']

export default {
  name: 'ShotDetail',
  components: { ShotAssets },
  props: {
    shot: { type: Object, required: true },
    characters: { type: Array, default: () => [] },
    progress: { type: Object, default: null },
    videoBusy: Boolean,
    imageBusy: Boolean
  },
  data() {
    return { draft: {} }
  },
  computed: {
    st() { return shotStatus(this.shot, this.progress) },
    media() {
      const p = this.shot.video_path || this.shot.img_path
      return p ? api.staticUrl(p) : ''
    },
    progressText() {
      if (this.progress && this.progress.step && this.progress.step !== 'done') return this.progress.msg || '生成中…'
      return '还没有视频和画面'
    },
    speakers() {
      const names = this.characters.map(c => c.name)
      const cur = this.shot.character_name
      return [...names, NARRATOR, ...(cur && !names.includes(cur) && cur !== NARRATOR ? [cur] : [])]
    }
  },
  watch: {
    shot: { immediate: true, handler: 'reset' }
  },
  methods: {
    reset() {
      const d = {}
      FIELDS.forEach(f => { d[f] = this.shot[f] === undefined || this.shot[f] === null ? '' : this.shot[f] })
      if (!d.character_name) d.character_name = NARRATOR
      if (d.duration === '') d.duration = undefined
      this.draft = d
    },
    save(field) {
      const value = this.draft[field]
      if (value === undefined) return
      this.$emit('save', this.shot, { [field]: value })
    }
  }
}
</script>

<style scoped>
.shot-detail { display: flex; flex-direction: column; gap: 16px; min-width: 0; }
.shot-detail__title { font-family: var(--font-serif); font-size: 20px; font-weight: 700; }
</style>
