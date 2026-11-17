<template>
  <div v-if="model" class="update-banner" role="status">
    <span class="update-banner__text">{{ model.text }}</span>
    <button v-if="model.hasNotes" type="button" class="update-banner__btn" @click="notesOpen = true">查看更新说明</button>
    <button type="button" class="update-banner__btn update-banner__btn--main" :disabled="working" @click="update">
      {{ working ? '下载中…' : '去更新' }}
    </button>
    <button type="button" class="update-banner__btn" :disabled="working" @click="later">稍后</button>
    <el-dialog :visible.sync="notesOpen" :title="'更新说明'" width="520px" append-to-body>
      <UpdateNotes :version="model.version" :notes="notes" :meta="meta" />
    </el-dialog>
  </div>
</template>

<script>
/**
 * 「有新版本」提示条：可稍后（记住被忽略的版本，下个版本再提示）/ 查看更新说明 / 去更新。
 * 状态来自 router/updateGate 的缓存（后端每个续租周期检查一次，这里每 60 秒读一次缓存，不联网）。
 * 样式与授权横幅同一套（粘在顶部，中性色），强制升级时由 UpdateRequiredScreen 接管，本条不显示。
 */
import { toastError, toastSuccess } from '@/utils/notify'
import { updateGate } from '@/router/updateGate'
import { formatPublishedAt, formatSize, readDismissed, startUpdate, updateBannerModel, writeDismissed } from './update'

const POLL_MS = 60 * 1000

function storage() {
  try { return window.localStorage } catch (_) { return null }
}

export default {
  name: 'UpdateBanner',
  data() {
    return { status: null, dismissed: readDismissed(storage()), notesOpen: false, working: false, timer: null, unsub: null }
  },
  computed: {
    model() { return updateBannerModel(this.status, this.dismissed) },
    latest() { return (this.status && this.status.latest) || {} },
    notes() { return this.latest.notes || '' },
    meta() {
      return [formatPublishedAt(this.latest.published_at), formatSize(this.latest.size)].filter(Boolean).join(' · ')
    }
  },
  created() {
    this.unsub = updateGate.subscribe(s => { this.status = s })
    this.refresh(false)
    this.timer = setInterval(() => this.refresh(true), POLL_MS)
  },
  beforeDestroy() {
    clearInterval(this.timer)
    if (this.unsub) this.unsub()
  },
  methods: {
    async refresh(force) {
      const s = await updateGate.check({ force })
      if (s) this.status = s
    },
    later() {
      if (!this.model) return
      this.dismissed = this.model.version
      writeDismissed(storage(), this.model.version)
    },
    async update() {
      if (this.working) return
      this.working = true
      try {
        const r = await startUpdate(this.latest, { desktop: window.dongaiDesktop, open: u => window.open(u, '_blank', 'noopener') })
        if (r.ok) toastSuccess(r.message)
        else toastError(null, r.message)
      } finally {
        this.working = false
      }
    }
  }
}
</script>

<style scoped>
.update-banner {
  display: flex;
  align-items: center;
  justify-content: center;
  flex-wrap: wrap;
  gap: 4px 12px;
  padding: 8px 16px;
  font-size: var(--fs-small);
  line-height: 1.5;
  background: var(--side);
  color: var(--ink);
  border-bottom: 1px solid var(--line);
}
.update-banner__text { min-width: 0; }
.update-banner__btn {
  flex: none;
  border: 1px solid currentColor;
  border-radius: var(--radius-nav);
  background: transparent;
  color: var(--ink-muted);
  padding: 2px 10px;
  font-size: var(--fs-small);
  cursor: pointer;
}
.update-banner__btn:hover { color: var(--ink); }
.update-banner__btn--main { color: var(--ink); font-weight: 500; }
.update-banner__btn:disabled { opacity: .6; cursor: default; }
</style>
