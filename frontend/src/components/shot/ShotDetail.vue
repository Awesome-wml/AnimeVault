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
    <p v-for="w in shot.style_warnings || []" :key="w" class="shot-detail__warn" role="alert">{{ w }}。</p>
    <p v-for="w in shot.prompt_warnings || []" :key="w" class="shot-detail__warn" role="alert">{{ w }}{{ w.includes('没有参考图') ? '，先在角色页生成参考图。' : '。' }}</p>
    <p v-if="failed" class="shot-detail__warn" role="alert">生成失败：{{ progressText }}</p>

    <MediaFrame v-if="!segment || shot.video_path || generating" :key="media" :src="media" :tone="shot.shot_no" ratio="16 / 9" :controls="!!shot.video_path" :label="progressText" />

    <div class="inline-actions">
      <BaseButton :loading="videoBusy" @click="$emit('generate-video', shot)">{{ shot.video_path ? '重新生成视频' : '生成视频' }}</BaseButton>
      <BaseButton variant="text" @click="$emit('manual-video', shot)">补录视频</BaseButton>
      <BaseButton variant="text" :loading="imageBusy" @click="$emit('generate-image', shot)">{{ hasPicture ? '重新生成画面' : '生成画面' }}</BaseButton>
      <BaseButton variant="text" @click="$emit('delete', shot)">{{ segment ? '删除这一段' : '删除镜头' }}</BaseButton>
    </div>

    <template v-if="segment">
      <div class="field-group">
        <span class="field-label">四格分镜（视频参考图：左上→右上→左下→右下 依次对应本段四个时间段）</span>
        <StoryboardCard :shot="shot" :busy="imageBusy" />
      </div>
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
    <div v-if="reviewText" class="field-group">
      <span class="field-label">成片回看（检测成片实际切了几个镜头，和提示词对比）</span>
      <p class="shot-detail__review" :class="{ 'shot-detail__review--off': shot.review && shot.review.ok === false }">{{ reviewText }}</p>
    </div>
    <div class="field-group">
      <span class="field-label">用到的资产</span>
      <ShotAssets :assets="shot.assets || []" :prev-frame="shot.prev_frame" />
    </div>

    <details class="fold fold--plain">
      <summary>提示词与生成参数</summary>
      <div class="fold__body">
        <FormField :label="segment ? '画面描述' : '视频提示词'" :hint="segment ? '参考图编号、台词表、时长和禁区在生成时按实际上传的参考图自动加上' : ''">
          <el-input v-model="draft.video_prompt" type="textarea" :autosize="{ minRows: 3, maxRows: 10 }" @change="save('video_prompt')" />
        </FormField>
        <div v-if="shot.final_video_prompt" class="field-group">
          <span class="field-label">发给视频模型的完整提示词（只读，保存后刷新）</span>
          <div class="shot-detail__prompt">
            <PromptRefText :text="shot.final_video_prompt" :assets="shot.assets || []" />
          </div>
        </div>
        <FormField v-if="segment" label="四格分镜文案" hint="由小镜头自动拼出（改小镜头后会重拼）；人物外观和画风在生成时自动加上">
          <el-input v-model="draft.storyboard_prompt" type="textarea" :autosize="{ minRows: 4, maxRows: 14 }" placeholder="拆分镜后自动生成" @change="save('storyboard_prompt')" />
        </FormField>
        <FormField v-else label="画面提示词" hint="生成画面（参考图）用">
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
 * 视频段（有 lines）：四格分镜图（视频参考图，S1–S4 对应时间段）、逐句编辑台词、段内小镜头时间轴、
 * 发给视频模型的完整提示词预览；没有视频也没在生成时顶部不放 16:9 预览框，四格图就是本段的画面。
 * 旧数据照旧：顶部首帧/视频预览，编辑整段台词与说话人。
 * 字段改完（失焦/选择）即 emit('save', shot, { 字段: 值 })，由页面提交。
 */
import { api } from '@/api'
import { fillStatus } from '@/components/base/status'
import { shotStatus, NARRATOR } from './status'
import { isSegment, pictureOf, sec, shotTitle } from './segment'
import ShotAssets from './ShotAssets.vue'
import PromptRefText from './PromptRefText.vue'
import LineEditor from './LineEditor.vue'
import BeatTimeline from './BeatTimeline.vue'
import StoryboardCard from './StoryboardCard.vue'

const FIELDS = ['text', 'character_name', 'video_prompt', 'prompt', 'duration', 'storyboard_prompt']

export default {
  name: 'ShotDetail',
  components: { ShotAssets, PromptRefText, LineEditor, BeatTimeline, StoryboardCard },
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
    hasPicture() { return !!pictureOf(this.shot) },
    /** 成片回看的一句话结论：计划几个小镜头、成片切了几个、切在哪几秒 */
    reviewText() {
      const r = this.shot.review
      if (!r || r.error || !Array.isArray(r.actual_cuts)) return ''
      const planned = (r.planned_cuts || []).length + 1
      const actual = r.actual_cuts.length + 1
      const at = r.actual_cuts.length ? `，切在 ${r.actual_cuts.map(t => Number(t).toFixed(1)).join('、')} 秒` : ''
      const longest = r.longest_shot_seconds ? `，最长的一个镜头 ${r.longest_shot_seconds} 秒` : ''
      return r.ok
        ? `按提示词切了 ${actual} 个镜头${at}${longest}。`
        : `提示词写了 ${planned} 个小镜头，成片切了 ${actual} 个${at}${longest}。具体偏差见上方提示。`
    },
    generating() {
      // 已有成片则不再视为生成中，避免残留进度覆盖成片预览与文案；终态失败不算生成中
      if (this.shot.video_path) return false
      return !!(this.progress && this.progress.step &&
        this.progress.step !== 'done' && this.progress.step !== 'failed')
    },
    failed() {
      return !!(this.progress && this.progress.step === 'failed')
    },
    /** 顶部预览：视频优先；旧数据没有视频时显示首帧，视频段的画面在下方四格分镜里 */
    media() {
      const p = this.shot.video_path || (this.segment ? '' : this.shot.img_path)
      return p ? api.staticUrl(p) : ''
    },
    progressText() {
      if (this.generating) return this.progress.msg || '生成中…'
      if (this.failed) return this.st.reason || this.progress.msg || '生成失败'
      return this.segment ? '还没有视频' : '还没有视频和画面'
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
.shot-detail__review { font-size: var(--fs-small); margin: 0; }
.shot-detail__review--off { color: var(--seal); }
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
