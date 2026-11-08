<template>
  <ProjectPage title="配音与字幕" :subtitle="subtitle">
    <template #actions>
      <BaseButton variant="text" :loading="srtLoading" @click="downloadSrt">下载字幕 SRT</BaseButton>
      <BaseButton :loading="assigning" @click="autoAssign">自动配音色</BaseButton>
      <BaseButton variant="primary" :loading="!!batch" :disabled="!rows.length" @click="generateAll">生成全部配音</BaseButton>
    </template>

    <div class="table-wrap">
      <el-table v-loading="loading" :data="rows" empty-text="这一集还没有分镜。先在小说页一键提取或在分镜页拆分镜。">
        <el-table-column prop="shot_no" label="镜头" width="72" />
        <el-table-column prop="speaker" label="说话人" width="110" />
        <el-table-column label="内容" min-width="300">
          <template slot-scope="{ row }"><div class="cell-ellipsis" :title="row.text">{{ row.text || '（没有台词）' }}</div></template>
        </el-table-column>
        <el-table-column label="音色" width="150">
          <template slot-scope="{ row }"><div class="cell-ellipsis" :title="row.voice">{{ row.voice }}</div></template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template slot-scope="{ row }"><StatusText :status="audio[row.id] ? 'voice_done' : 'voice_none'" /></template>
        </el-table-column>
        <el-table-column label="操作" width="170">
          <template slot-scope="{ row }">
            <div class="inline-actions">
              <BaseButton variant="text" strong :loading="busyId === row.id" :disabled="!row.text || (!!busyId && busyId !== row.id)" @click="generate(row)">
                {{ audio[row.id] ? '重新配音' : '生成配音' }}
              </BaseButton>
              <BaseButton v-if="audio[row.id]" variant="text" @click="play(row)">试听</BaseButton>
            </div>
          </template>
        </el-table-column>
      </el-table>
    </div>
    <p class="note">说话人的音色在角色页设置；旁白和没有绑定音色的角色使用默认音色。字幕按整部作品的镜头顺序生成。</p>
  </ProjectPage>
</template>

<script>
/**
 * 配音与字幕：当前剧集每个镜头的说话人、台词、音色；逐条或全部生成配音（后端按说话人绑定的音色），
 * 自动给角色配音色，下载整部作品的 SRT 字幕。
 * 后端分镜列表不返回 audio_path，所以“已配音”只记录本次打开页面后生成的。
 */
import { mapGetters } from 'vuex'
import { api } from '@/api'
import { runAction, toastError, toastSuccess, toastWarning } from '@/utils/notify'
import { loadVoices, voiceName, DEFAULT_VOICE } from '@/components/voice/voices'
import { downloadSrt } from '@/components/project/exports'
import { speakerOf, NARRATOR } from '@/components/shot/status'
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
    rows() {
      const byName = {}
      this.characters.forEach(c => { byName[c.name] = c })
      const fallback = `${voiceName(this.voices, DEFAULT_VOICE)}（默认）`
      return this.shots.map(s => {
        const speaker = speakerOf(s)
        const c = speaker !== NARRATOR ? byName[speaker] : null
        return { ...s, speaker, voice: c && c.voice_name ? voiceName(this.voices, c.voice_name) : fallback }
      })
    },
    subtitle() {
      const parts = this.episode ? [this.episode.name] : []
      if (this.batch) parts.push(`正在配音 ${this.batch.done} / ${this.batch.total}`)
      return parts.join(' · ')
    }
  },
  watch: {
    episodeId: { immediate: true, handler: 'loadShots' }
  },
  created() {
    this.loadCharacters()
    loadVoices().then(v => { this.voices = v }, e => toastError(e, '音色列表加载失败'))
  },
  beforeDestroy() {
    if (this.player) this.player.pause()
    if (this.batch) this.batch.cancelled = true
  },
  methods: {
    async loadShots() {
      this.loading = true
      try {
        const list = await api.shot.list(this.pid, this.episodeId)
        this.shots = Array.isArray(list) ? list : []
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
      const res = await api.tts.generate({ shot_id: row.id, text: row.text })
      this.$set(this.audio, row.id, res.data.audio_path)
    },
    async generate(row) {
      this.busyId = row.id
      await runAction(() => this.requestVoice(row), { success: `镜头 ${row.shot_no} 配音完成`, error: '配音失败' })
      this.busyId = ''
    },
    async generateAll() {
      const todo = this.rows.filter(r => r.text)
      if (!todo.length) { toastWarning('没有可配音的台词'); return }
      const batch = { total: todo.length, done: 0, failed: 0, cancelled: false }
      this.batch = batch
      for (const row of todo) {
        if (batch.cancelled) return
        this.busyId = row.id
        try {
          await this.requestVoice(row)
        } catch (e) {
          batch.failed++
          toastError(e, `镜头 ${row.shot_no} 配音失败`)
        }
        batch.done++
      }
      this.busyId = ''
      this.batch = null
      toastSuccess(batch.failed ? `配音完成，${batch.failed} 条失败` : `全部 ${batch.total} 条配音完成`)
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
