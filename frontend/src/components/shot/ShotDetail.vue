<template>
  <section class="shot-detail" :aria-label="`${title}详情`">
    <div class="section__head">
      <h2 class="shot-detail__title">{{ title }}</h2>
      <StatusText class="small" :status="st.status" :n="st.n" />
    </div>
    <p v-if="segment" class="shot-detail__meta">
      {{ sec(shot.duration) }} 秒 · 朗读 {{ sec(shot.speech_seconds) }} 秒 ·
      <StatusText :status="fill.key" :n="fill.n" />
      <template v-if="shot.mood"> · {{ shot.mood }}</template>
      · 一次视频生成
    </p>
    <p v-for="w in shot.prompt_warnings || []" :key="w" class="shot-detail__warn" role="alert">{{ w }}{{ w.includes('没有参考图') ? '，先在角色页生成参考图。' : '。' }}</p>

    <MediaFrame :key="media" :src="media" :tone="shot.shot_no" ratio="16 / 9" :controls="!!shot.video_path" :label="progressText" />

    <div class="inline-actions">
      <BaseButton :loading="videoBusy" @click="$emit('generate-video', shot)">{{ shot.video_path ? '重新生成视频' : '生成视频' }}</BaseButton>
      <BaseButton variant="text" @click="$emit('manual-video', shot)">补录视频</BaseButton>
      <BaseButton variant="text" :loading="imageBusy" @click="$emit('generate-image', shot)">{{ shot.img_path ? '重新生成画面' : '生成画面' }}</BaseButton>
      <BaseButton variant="text" @click="$emit('delete', shot)">{{ segment ? '删除这一段' : '删除镜头' }}</BaseButton>
    </div>

    <template v-if="segment">
      <div class="field-group">
        <span class="field-label">本段台词（逐句，起止秒按朗读时长自动校正）</span>
        <LineEditor :lines="shot.lines" :speakers="speakers" @change="lines => $emit('save', shot, { lines })" />
      </div>
      <div v-if="shot.beats && shot.beats.length" class="field-group">
        <span class="field-label">段内小镜头</span>
        <BeatTimeline :beats="shot.beats" :duration="Number(shot.duration) || 15" />
      </div>
    </template>
    <template v-else>
    <FormField label="台词">
      <el-input v-model="draft.text" type="textarea" :autosize="{ minRows: 2, maxRows: 6 }" placeholder="台词 / 旁白" @change="save('text')" />
    </FormField>
    <FormField label="说话人">
      <el-select v-model="draft.character_name" filterable allow-create @change="save('character_name')">
        <el-option v-for="name in speakers" :key="name" :label="name" :value="name"></el-option>
      </el-select>
    </FormField>
    </template>
    <div class="field-group">
      <span class="field-label">用到的资产</span>
      <ShotAssets :assets="shot.assets || []" />
    </div>

    <details class="fold fold--plain">
      <summary>提示词与生成参数</summary>
      <div class="fold__body">
        <FormField :label="segment ? '画面描述' : '视频提示词'" :hint="segment ? '参考图编号、台词表、时长和禁区在生成时按实际上传的参考图自动加上' : ''">
          <el-input v-model="draft.video_prompt" type="textarea" :autosize="{ minRows: 3, maxRows: 10 }" @change="save('video_prompt')" />
        </FormField>
        <div v-if="shot.final_video_prompt" class="field-group">
          <span class="field-label">发给视频模型的完整提示词（只读，保存后刷新）</span>
          <pre class="shot-detail__prompt">{{ shot.final_video_prompt }}</pre>
        </div>
        <FormField label="画面提示词" hint="生成画面（参考图）用">
          <el-input v-model="draft.prompt" type="textarea" :autosize="{ minRows: 3, maxRows: 10 }" placeholder="豆包自动化提示词" @change="save('prompt')" />
        </FormField>
        <div class="form-row">
          <FormField label="时长（秒）">
            <el-input-number v-model="draft.duration" :min="0.5" :max="30" :step="0.5" controls-position="right" @change="save('duration')" />
          </FormField>
          <FormField label="模型" hint="整部作品统一，在风格页更改">
            <el-select value="" disabled :placeholder="modelName" />
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
 * 单个镜头/视频段的详情：播放/预览、生成与补录、台词、用到的资产、提示词。
 * 视频段（有 lines）：逐句编辑台词、段内小镜头时间轴、发给视频模型的完整提示词预览；旧数据照旧编辑整段台词与说话人。
 * 字段改完（失焦/选择）即 emit('save', shot, { 字段: 值 })，由页面提交。
 */
import { api } from '@/api'
import { fillStatus } from '@/components/base/status'
import { shotStatus, NARRATOR } from './status'
import { isSegment, sec, shotTitle } from './segment'
import ShotAssets from './ShotAssets.vue'
import LineEditor from './LineEditor.vue'
import BeatTimeline from './BeatTimeline.vue'

const FIELDS = ['text', 'character_name', 'video_prompt', 'prompt', 'duration']

export default {
  name: 'ShotDetail',
  components: { ShotAssets, LineEditor, BeatTimeline },
  props: {
    shot: { type: Object, required: true },
    characters: { type: Array, default: () => [] },
    modelName: { type: String, default: 'Seedance 2.0 Fast' },
    progress: { type: Object, default: null },
    videoBusy: Boolean,
    imageBusy: Boolean
  },
  data() {
    return { draft: {} }
  },
  computed: {
    st() { return shotStatus(this.shot, this.progress) },
    segment() { return isSegment(this.shot) },
    title() { return shotTitle(this.shot) },
    fill() { return fillStatus(this.shot.fill_rate) },
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
      const extra = [this.shot.character_name, ...(this.shot.lines || []).map(ln => ln.speaker)]
        .filter(n => n && n !== NARRATOR && !names.includes(n))
      return [...names, NARRATOR, ...new Set(extra)]
    }
  },
  watch: {
    shot: { immediate: true, handler: 'reset' }
  },
  methods: {
    sec,
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
.shot-detail__meta { color: var(--ink-muted); font-size: var(--fs-small); }
.shot-detail__warn { color: var(--seal); font-size: var(--fs-small); }
.shot-detail__prompt {
  margin: 0;
  padding: 10px 12px;
  border: 1px solid var(--line);
  border-radius: var(--radius);
  background: var(--side);
  font-family: var(--font-sans);
  font-size: var(--fs-caption);
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 320px;
  overflow: auto;
}
</style>
