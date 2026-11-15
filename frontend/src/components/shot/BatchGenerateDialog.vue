<template>
  <el-dialog title="批量生成视频" :visible="visible" width="640px" :close-on-click-modal="false" @update:visible="v => $emit('update:visible', v)" @open="load">
    <div v-loading="loading" class="form-stack">
      <template v-if="status">
        <p>
          共 {{ total }} 个镜头，已出视频 {{ total - pending }} 个，待生成 {{ pending }} 个。
          本次最多可生成 <strong>{{ maxCount }}</strong> 条。
        </p>
        <FormField label="本次生成" hint="按镜头顺序，跳过已有视频的镜头">
          <el-input-number v-model="count" :min="1" :max="maxCount || 1" :disabled="!maxCount" controls-position="right" />
        </FormField>
        <FormField label="承接上一条" hint="同场相邻镜头以上一条尾帧做首帧参考；并行或上一条未成片时自动跳过">
          <el-switch v-model="usePrev" />
        </FormField>
        <div class="table-wrap">
          <el-table :data="status.accounts || []" size="small" empty-text="还没有视频账号">
            <el-table-column prop="name" label="账号" min-width="140" />
            <el-table-column label="额度" min-width="220">
              <template slot-scope="{ row }"><StatusText :status="quotaStatus(row).key" :n="quotaStatus(row).vars" /></template>
            </el-table-column>
            <el-table-column label="状态" width="80">
              <template slot-scope="{ row }"><StatusText :status="row.available ? 'enabled' : 'disabled'" :text="row.available ? '可用' : (row.enabled ? '已满' : '停用')" /></template>
            </el-table-column>
            <el-table-column label="登录有效期" width="110">
              <template slot-scope="{ row }"><StatusText :status="cookieStatus(row.cookie_days)" :n="row.cookie_days" /></template>
            </el-table-column>
          </el-table>
        </div>
        <p v-if="maxCount < pending" class="note">{{ shortNote }}</p>
      </template>
    </div>
    <template #footer>
      <BaseButton variant="text" to="/settings/accounts">管理视频账号</BaseButton>
      <BaseButton @click="$emit('update:visible', false)">取消</BaseButton>
      <BaseButton variant="primary" :loading="running" :disabled="!maxCount" @click="start">开始生成</BaseButton>
    </template>
  </el-dialog>
</template>

<script>
/** 批量生成视频（豆包自动化）：显示账号配额，选择本次条数后提交。完成后 emit('done', 结果)。 */
import { MessageBox } from 'element-ui'
import { api } from '@/api'
import { cookieStatus, quotaStatus } from '@/components/base/status'
import { toastError } from '@/utils/notify'

export default {
  name: 'BatchGenerateDialog',
  props: {
    visible: Boolean,
    projectId: { type: String, required: true },
    total: { type: Number, default: 0 },
    pending: { type: Number, default: 0 }
  },
  data() {
    return { loading: false, running: false, status: null, count: 1, usePrev: true }
  },
  computed: {
    quota() { return (this.status && this.status.total_available_quota) || 0 },
    // 并行多账号分摊：parallel_max 是各账号 min(剩余额度, 5 标签页) 求和后的本批总条数
    batchMax() {
      const s = this.status || {}
      return s.parallel_max === undefined || s.parallel_max === null ? this.quota : Math.min(this.quota, s.parallel_max)
    },
    maxCount() { return Math.min(this.batchMax, this.pending) },
    shortNote() {
      if (!this.maxCount) return '所有账号的额度都已用完，暂时不能生成。'
      if (this.quota < this.pending) return `剩余额度不够全部生成，本次最多 ${this.maxCount} 条。`
      return `一次并行最多生成 ${this.maxCount} 条，其余镜头请生成完后再继续。`
    }
  },
  methods: {
    cookieStatus,
    quotaStatus,
    async load() {
      this.loading = true
      try {
        const res = await api.video.getAccountStatus()
        this.status = res.data
        this.count = Math.max(1, this.maxCount)
      } catch (e) {
        toastError(e, '账号状态加载失败')
      } finally {
        this.loading = false
      }
    },
    async start() {
      this.running = true
      try {
        const res = await api.video.generateBatch(this.projectId, this.count, true, this.usePrev)
        const d = res.data || {}
        const lines = [`共 ${d.total_shots} 条：成功 ${d.success_count}，失败 ${d.failed_count}`]
        ;(d.results || []).forEach(r => lines.push(`${r.account_name}：成功 ${r.success_count}，失败 ${r.failed_count}`))
        this.$emit('update:visible', false)
        this.$emit('done', d)
        // MessageBox 不渲染换行，按行拼成段落
        const h = this.$createElement
        MessageBox.alert(h('div', lines.map(l => h('p', l))), '生成结果', { confirmButtonText: '知道了', type: d.failed_count > 0 ? 'warning' : 'success' })
      } catch (e) {
        toastError(e, '批量生成失败')
      } finally {
        this.running = false
      }
    }
  }
}
</script>
