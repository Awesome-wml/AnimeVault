<template>
  <div v-if="model" class="update-required" role="alertdialog" aria-modal="true" aria-labelledby="update-required-title">
    <main class="update-required__card">
      <span class="update-required__brand serif">DongAI</span>
      <PageHeader id="update-required-title" title="需要升级才能继续使用" :subtitle="model.message" />
      <dl class="update-required__versions">
        <div class="update-required__row"><dt>当前版本</dt><dd>{{ model.currentVersion }}</dd></div>
        <div v-if="model.minVersion" class="update-required__row"><dt>需要的最低版本</dt><dd>{{ model.minVersion }}</dd></div>
        <div v-if="model.latestVersion" class="update-required__row"><dt>最新版本</dt><dd>{{ model.latestVersion }}</dd></div>
      </dl>
      <UpdateNotes v-if="model.latestVersion" :version="model.latestVersion" :notes="model.notes" :meta="meta" />
      <p class="update-required__tip">你的作品和本地数据都还在，升级后即可继续使用。</p>
      <div class="update-required__actions">
        <BaseButton variant="primary" size="lg" :loading="working" :disabled="!model.canDownload" @click="update">下载更新</BaseButton>
        <BaseButton variant="text" :loading="checking" @click="recheck">我已升级，重新检查</BaseButton>
      </div>
      <p v-if="!model.canDownload" class="update-required__tip">暂时没有获取到下载地址，请联网后点「重新检查」，或联系我们。</p>
    </main>
  </div>
</template>

<script>
/**
 * 强制升级全屏页：服务端要求最低版本、更新检查 force=true 或接口返回 UPDATE_REQUIRED 时盖住整个应用。
 * 除授权/更新接口外后端一律 403，所以这里不再渲染业务页面；本地数据不动。
 */
import { api } from '@/api'
import { toastError, toastInfo, toastSuccess } from '@/utils/notify'
import { updateGate } from '@/router/updateGate'
import UpdateNotes from './UpdateNotes.vue'
import { formatPublishedAt, formatSize, requiredScreenModel, startUpdate } from './update'

export default {
  name: 'UpdateRequiredScreen',
  components: { UpdateNotes },
  data() {
    return { status: null, working: false, checking: false, unsub: null }
  },
  computed: {
    model() { return requiredScreenModel(this.status) },
    meta() {
      const l = (this.status && this.status.latest) || {}
      return [formatPublishedAt(l.published_at), formatSize(l.size)].filter(Boolean).join(' · ')
    }
  },
  created() {
    this.status = updateGate.peek()
    this.unsub = updateGate.subscribe(s => { this.status = s })
    updateGate.check({ force: false })
  },
  beforeDestroy() {
    if (this.unsub) this.unsub()
  },
  methods: {
    async update() {
      if (this.working) return
      this.working = true
      try {
        const latest = (this.status && this.status.latest) || {}
        const r = await startUpdate(latest, { desktop: window.dongaiDesktop, open: u => window.open(u, '_blank', 'noopener') })
        if (r.ok) toastSuccess(r.message)
        else toastError(null, r.message)
      } finally {
        this.working = false
      }
    },
    async recheck() {
      if (this.checking) return
      this.checking = true
      try {
        const s = await api.update.check()
        updateGate.set(s)
        if (s && s.update_required) toastInfo('仍需升级，请先下载并安装新版本')
      } catch (e) {
        toastError(null, '检查失败，请稍后重试')
      } finally {
        this.checking = false
      }
    }
  }
}
</script>

<style scoped>
.update-required {
  position: fixed;
  inset: 0;
  z-index: 3000;
  display: flex;
  justify-content: center;
  overflow: auto;
  padding: 48px 20px;
  background: var(--paper);
}
.update-required__card { width: 100%; max-width: 560px; display: flex; flex-direction: column; gap: 24px; height: max-content; }
.update-required__brand { align-self: flex-start; font-size: 20px; font-weight: 700; }
.update-required__versions {
  border: 1px solid var(--line);
  border-radius: var(--radius);
  background: var(--surface);
}
.update-required__row { display: flex; gap: 16px; padding: 12px 16px; font-size: var(--fs-body); }
.update-required__row + .update-required__row { border-top: 1px solid var(--line); }
.update-required__row dt { flex: none; width: 120px; color: var(--ink-muted); }
.update-required__row dd { min-width: 0; word-break: break-all; }
.update-required__tip { font-size: var(--fs-small); color: var(--ink-muted); }
.update-required__actions { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
</style>
