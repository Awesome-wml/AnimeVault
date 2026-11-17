<template>
  <el-drawer :visible="visible" title="版本详情" size="620px" append-to-body
             @update:visible="v => $emit('update:visible', v)" @open="load">
    <div v-loading="loading" class="drawer" data-testid="release-drawer">
      <template v-if="rel">
        <div class="drawer__head">
          <b class="mono" data-testid="drawer-version">{{ rel.version }}</b>
          <StatusTag kind="release" :status="rel.status" />
        </div>

        <el-descriptions :column="1" size="small" border>
          <el-descriptions-item label="渠道">{{ channelText }}</el-descriptions-item>
          <el-descriptions-item label="平台">{{ platformText }}</el-descriptions-item>
          <el-descriptions-item label="强制升级线">
            <span data-testid="drawer-min">{{ rel.min_supported || '无' }}</span>
          </el-descriptions-item>
          <el-descriptions-item label="文件大小">{{ sizeText }}</el-descriptions-item>
          <el-descriptions-item label="创建">{{ fmt(rel.created_at) }} · {{ creator }}</el-descriptions-item>
          <el-descriptions-item label="发布时间">{{ rel.published_at ? fmt(rel.published_at) : '未发布' }}</el-descriptions-item>
          <el-descriptions-item v-if="rel.withdrawn_at" label="撤回时间">{{ fmt(rel.withdrawn_at) }}</el-descriptions-item>
        </el-descriptions>

        <section class="drawer__sec">
          <h3 class="section-title">更新说明</h3>
          <pre class="notes" data-testid="drawer-notes">{{ rel.notes || '（无）' }}</pre>
        </section>

        <section class="drawer__sec">
          <h3 class="section-title">下载地址</h3>
          <div class="copy-row">
            <code class="mono copy-row__text" data-testid="drawer-url">{{ rel.url }}</code>
            <CopyButton :text="rel.url" label="复制地址" data-testid="copy-url" />
          </div>
        </section>

        <section class="drawer__sec">
          <h3 class="section-title">sha256</h3>
          <div class="copy-row">
            <code class="mono copy-row__text" data-testid="drawer-sha256">{{ rel.sha256 }}</code>
            <CopyButton :text="rel.sha256" label="复制 sha256" data-testid="copy-sha256" />
          </div>
        </section>

        <section v-if="canWrite && (acts.edit || acts.publish || acts.withdraw)" class="drawer__sec">
          <h3 class="section-title">操作</h3>
          <div class="inline-actions">
            <el-button v-if="acts.edit" size="small" data-testid="drawer-edit" @click="$emit('action', 'edit', rel)">编辑草稿</el-button>
            <el-button v-if="acts.publish" size="small" type="primary" data-testid="drawer-publish" @click="$emit('action', 'publish', rel)">发布</el-button>
            <el-button v-if="acts.withdraw" size="small" type="danger" plain data-testid="drawer-withdraw" @click="$emit('action', 'withdraw', rel)">撤回</el-button>
          </div>
        </section>
      </template>
    </div>
  </el-drawer>
</template>

<script>
import { api } from '@/api'
import { can } from '@/config/roles'
import { CHANNELS, PLATFORMS } from '@/config/releases'
import { operatorName } from '@/utils/license'
import { formatSize, releaseActions, releaseLabel } from '@/utils/release'
import { formatTime } from '@/utils/time'

export default {
  name: 'ReleaseDrawer',
  props: {
    visible: { type: Boolean, default: false },
    releaseId: { type: String, default: '' }
  },
  data() { return { rel: null, loading: false } },
  computed: {
    canWrite() { return can(this.$store.getters.role, 'release.write') },
    acts() { return releaseActions(this.rel && this.rel.status) },
    channelText() { return releaseLabel(CHANNELS, this.rel.channel) },
    platformText() { return releaseLabel(PLATFORMS, this.rel.platform) },
    sizeText() { return `${formatSize(this.rel.size)}（${this.rel.size} 字节）` },
    creator() { return operatorName(this.rel.created_by_username, this.rel.created_by) || '-' }
  },
  methods: {
    fmt: formatTime,
    async load() {
      if (!this.releaseId) return
      if (this.rel && this.rel.id !== this.releaseId) this.rel = null
      this.loading = true
      try {
        this.rel = await api.releases.get(this.releaseId)
      } catch (e) { /* 拦截器已提示 */ } finally {
        this.loading = false
      }
    }
  }
}
</script>

<style scoped>
.drawer { padding: 0 20px 28px; display: flex; flex-direction: column; gap: 20px; min-height: 200px; }
.drawer__head { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.drawer__sec { display: flex; flex-direction: column; gap: 10px; }
.section-title { font-size: 15px; font-weight: 600; margin: 0; }
.notes { margin: 0; padding: 10px 12px; background: var(--side); border-radius: var(--radius); white-space: pre-wrap; word-break: break-word; font-family: var(--font-sans); line-height: var(--lh-body); }
.copy-row { display: flex; align-items: flex-start; gap: 10px; }
.copy-row__text { flex: 1; min-width: 0; padding: 6px 10px; background: var(--side); border-radius: var(--radius); word-break: break-all; font-size: var(--fs-small); }
</style>
