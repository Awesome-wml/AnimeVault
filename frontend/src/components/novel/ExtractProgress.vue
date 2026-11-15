<template>
  <section v-if="progress" class="extract-progress" role="status" aria-live="polite" aria-label="提取进度">
    <StatusText :status="status" :n="vars" />
    <span v-if="progress.running" class="extract-progress__time">已用 {{ elapsedText }}</span>
    <BaseButton v-if="!progress.running" variant="text" @click="$emit('close')">关闭</BaseButton>
  </section>
</template>

<script>
/**
 * 一键提取 / 拆分镜的分阶段进度（小说页）。数据由 splitProgress.js 的 extractTask 维护：
 *   { running, stage: 'script'|'assets'|'shots'|'done'|'failed', chars, chunk, total, message, startedAt }
 * chars：SSE 接口（转剧本、资产提取）已接收的模型输出字数。剧本页也用它显示转剧本进度（长文分块时带第 x/n 块）。
 * 文案与颜色在 status.js 的 extract_* 里统一定义。
 */
export default {
  name: 'ExtractProgress',
  props: { progress: { type: Object, default: null } },
  data() {
    return { now: Date.now(), timer: null }
  },
  computed: {
    status() {
      const p = this.progress
      if (p.stage === 'script') {
        if (p.total > 1) return 'script_converting_chunk'
        return p.chars ? 'script_converting_chars' : 'script_converting'
      }
      if (p.stage === 'assets') return p.chars ? 'extract_assets_chars' : 'extract_assets'
      if (p.stage === 'shots') {
        if (p.total > 1) return p.chars ? 'extract_shots_chunk_chars' : 'extract_shots_chunk'
        return p.chars ? 'extract_shots_chars' : 'extract_shots'
      }
      return p.stage === 'failed' ? 'extract_failed' : 'extract_done'
    },
    vars() {
      const p = this.progress
      return { chunk: p.chunk, total: p.total, chars: (p.chars || 0).toLocaleString(), n: p.message }
    },
    elapsedText() {
      const s = Math.max(0, Math.round((this.now - this.progress.startedAt) / 1000))
      return s < 60 ? `${s} 秒` : `${Math.floor(s / 60)} 分 ${s % 60} 秒`
    }
  },
  mounted() {
    this.timer = setInterval(() => { this.now = Date.now() }, 1000)
  },
  beforeDestroy() {
    clearInterval(this.timer)
  }
}
</script>

<style scoped>
.extract-progress {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px 16px;
  padding: 10px 14px;
  border: 1px solid var(--line);
  border-radius: var(--radius);
  background: var(--surface);
  font-size: var(--fs-body);
}
.extract-progress >>> .status-text { white-space: normal; }
.extract-progress__time { color: var(--ink-muted); font-size: var(--fs-small); }
</style>
