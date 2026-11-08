<template>
  <ProjectPage title="配音与字幕" :subtitle="subtitle">
    <template #actions>
      <BaseButton variant="text" :loading="srtLoading" @click="downloadSrt">下载字幕 SRT</BaseButton>
      <BaseButton :loading="assigning" @click="autoAssign">自动配音色</BaseButton>
      <BaseButton variant="primary" :loading="running" :disabled="!segments.length" @click="generateAll">{{ running ? progressText(batch, '正在配音') : '生成全部配音' }}</BaseButton>
    </template>

    <BatchProgress :task.sync="batch" running-text="正在配音" done-text="配音完成" unit="条" title="批量配音进度" />

    <div class="table-wrap">
      <el-table v-loading="loading" :data="rows" row-key="key" :span-method="span" empty-text="这一集还没有分镜。先在小说页一键提取或在分镜页拆分镜。">
        <el-table-column label="段" width="84">
          <template slot-scope="{ row }">{{ row.title }}</template>
        </el-table-column>
        <el-table-column label="说话人" width="130">
          <template slot-scope="{ row }">{{ row.speakerText }}</template>
        </el-table-column>
        <el-table-column label="内容" min-width="280">
          <template slot-scope="{ row }"><div class="cell-ellipsis" :title="row.text">{{ row.text || '（没有台词）' }}</div></template>
        </el-table-column>
        <el-table-column label="段内起止" width="110">
          <template slot-scope="{ row }">{{ row.range }}</template>
        </el-table-column>
        <el-table-column label="音色" width="140">
          <template slot-scope="{ row }"><div class="cell-ellipsis" :title="row.voice">{{ row.voice }}</div></template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template slot-scope="{ row }"><StatusText :status="audio[row.id] ? 'voice_done' : 'voice_none'" /></template>
        </el-table-column>
        <el-table-column label="操作" width="170">
          <template slot-scope="{ row }">
            <div class="inline-actions">
              <BaseButton variant="text" strong :loading="busyId === row.id" :disabled="!row.shotText || running || (!!busyId && busyId !== row.id)" @click="generate(row)">
                {{ audio[row.id] ? '重新配音' : '生成配音' }}
              </BaseButton>
              <BaseButton v-if="audio[row.id]" variant="text" @click="play(row)">试听</BaseButton>
            </div>
          </template>
        </el-table-column>
      </el-table>
    </div>
    <p class="note">按句显示：说话人的音色在角色页设置，旁白和没有绑定音色的角色使用默认音色。一段配一条音频——逐句生成后按段内起止拼起来，句间留白、补齐到段时长。字幕按整部作品逐句生成。</p>
  </ProjectPage>
</template>

<script>
/**
 * 配音与字幕：当前剧集按句列出（所属段、说话人、台词、段内起止、音色）；配音按段生成（后端逐句合成、按段内时间拼接），
 * 自动给角色配音色，下载整部作品的 SRT 字幕。旧数据（没有逐句台词）一个镜头一行。
 */
import { mapGetters } from 'vuex'
import { api } from '@/api'
import { runAction, toastError, toastWarning } from '@/utils/notify'
import { batchRun, progressText, isRunning } from '@/utils/batchRun'
import { loadVoices, voiceName, DEFAULT_VOICE } from '@/components/voice/voices'
import { downloadSrt } from '@/components/project/exports'
import { speakerOf, NARRATOR } from '@/components/shot/status'
import { isSegment, lineSpeaker, shotTitle, timeRange } from '@/components/shot/segment'
import ProjectPage from './ProjectPage.vue'

export default {
  name: 'VoicePage',
  components: { ProjectPage },
  props: { pid: { type: String, required: true }, ep: { type: String, default: '' } },
  data() {
    return {
      loading: false,
      shots: [],
      characters: [],
      voices: [],
      audio: {},
      busyId: '',
      batch: null,
      assigning: false,
      srtLoading: false
    }
  },
  computed: {
    ...mapGetters('project', { episode: 'currentEpisode' }),
    episodeId() { return this.ep || (this.episode ? this.episode.id : '') },
    running() { return isRunning(this.batch) },
    /** 一句一行；同一段的“段 / 状态 / 操作”三列合并（span） */
    rows() {
      const byName = {}
      this.characters.forEach(c => { byName[c.name] = c })
      const fallback = `${voiceName(this.voices, DEFAULT_VOICE)}（默认）`
      const voiceOf = speaker => {
        const c = speaker && speaker !== NARRATOR ? byName[speaker] : null
        return c && c.voice_name ? voiceName(this.voices, c.voice_name) : fallback
      }
      const out = []
      this.shots.forEach(s => {
        const base = { id: s.id, shot_no: s.shot_no, title: shotTitle(s), shotText: s.text }
        if (isSegment(s)) {
          s.lines.forEach((ln, i) => out.push({
            ...base, key: `${s.id}:${i}`, first: i === 0, span: s.lines.length,
            speakerText: lineSpeaker(ln), text: ln.text, range: timeRange(ln),
            voice: voiceOf(ln.kind === 'narration' ? NARRATOR : ln.speaker)
          }))
        } else {
          const speaker = speakerOf(s)
          out.push({ ...base, key: s.id, first: true, span: 1, speakerText: speaker, text: s.text, range: '—', voice: voiceOf(speaker) })
        }
      })
      return out
    },
    /** 每段只生成一条配音 */
    segments() {
      return this.rows.filter(r => r.first)
    },
    subtitle() {
      return this.episode ? this.episode.name : ''
    }
  },
  watch: {
    episodeId: { immediate: true, handler: 'onEpisode' }
  },
  created() {
    this.loadCharacters()
    loadVoices().then(v => { this.voices = v }, e => toastError(e, '音色列表加载失败'))
  },
  beforeDestroy() {
    if (this.player) this.player.pause()
  },
  methods: {
    progressText,
    /** 换剧集：上一集的批量任务停掉 */
    onEpisode() {
      if (this.batch) this.batch.cancel()
      this.batch = null
      this.loadShots()
    },
    async loadShots() {
      this.loading = true
      try {
        const list = await api.shot.list(this.pid, this.episodeId)
        this.shots = Array.isArray(list) ? list : []
        const audio = {}
        this.shots.forEach(s => { if (s.audio_path) audio[s.id] = s.audio_path })
        this.audio = audio
      } catch (e) {
        toastError(e, '分镜加载失败')
      } finally {
        this.loading = false
      }
    },
    async loadCharacters() {
      try {
        const list = await api.character.list(this.pid)
        this.characters = Array.isArray(list) ? list : []
      } catch (e) {
        toastError(e, '角色列表加载失败')
      }
    },
    /** 生成一条；voice_name 留空，由后端按说话人绑定的音色选择 */
    async requestVoice(row) {
      this.busyId = row.id
      try {
        const res = await api.tts.generate({ shot_id: row.id, text: row.shotText })
        this.$set(this.audio, row.id, res.data.audio_path)
      } finally {
        if (this.busyId === row.id) this.busyId = ''
      }
    },
    async generate(row) {
      await runAction(() => this.requestVoice(row), { success: `${row.title}配音完成`, error: '配音失败' })
    },
    /** 逐条配音（utils/batchRun 串行），进度和失败重试见 BatchProgress */
    generateAll() {
      if (this.running) return
      const todo = this.segments.filter(r => r.shotText)
      if (!todo.length) { toastWarning('没有可配音的台词'); return }
      this.batch = batchRun(todo, row => this.requestVoice(row), { label: row => row.title })
    },
    span({ row, columnIndex }) {
      if (![0, 5, 6].includes(columnIndex)) return [1, 1]
      return row.first ? [row.span, 1] : [0, 0]
    },
    play(row) {
      if (this.player) this.player.pause()
      this.player = new Audio(api.staticUrl(this.audio[row.id]))
      this.player.play().catch(e => toastError(e, '无法播放'))
    },
    async autoAssign() {
      this.assigning = true
      const ok = await runAction(() => api.tts.autoAssign(this.pid), {
        success: res => (res && res.message) || '已自动配好音色',
        error: '自动配音色失败'
      })
      this.assigning = false
      if (ok) this.loadCharacters()
    },
    async downloadSrt() {
      this.srtLoading = true
      await downloadSrt(this.pid)
      this.srtLoading = false
    }
  }
}
</script>
