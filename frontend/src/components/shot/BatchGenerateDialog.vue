<template>
  <el-dialog title="批量生成视频" :visible="visible" width="640px" :close-on-click-modal="false" @update:visible="v => $emit('update:visible', v)" @open="load">
    <div v-loading="loading" class="form-stack">
      <template v-if="status">
        <p>
          共 {{ total }} 个镜头，已出视频 {{ total - pending }} 个，待生成 {{ pending }} 个。
          今日可用配额 <strong>{{ quota }}</strong> 条。
        </p>
        <FormField label="本次生成" hint="按镜头顺序，跳过已有视频的镜头">
          <el-input-number v-model="count" :min="1" :max="maxCount || 1" :disabled="!maxCount" controls-position="right" />
        </FormField>
        <div class="table-wrap">
          <el-table :data="status.accounts || []" size="small" empty-text="还没有视频账号">
            <el-table-column prop="name" label="账号" min-width="140" />
            <el-table-column label="今日已用" width="96">
              <template slot-scope="{ row }">{{ row.today_used }} / {{ row.daily_limit }}</template>
            </el-table-column>
            <el-table-column prop="remaining" label="剩余" width="70" />
            <el-table-column label="状态" width="80">
              <template slot-scope="{ row }"><StatusText :status="row.available ? 'enabled' : 'disabled'" :text="row.available ? '可用' : '已满'" /></template>
            </el-table-column>
            <el-table-column label="登录有效期" width="110">
              <template slot-scope="{ row }"><StatusText :status="cookieStatus(row.cookie_days)" :n="row.cookie_days" /></template>
            </el-table-column>
          </el-table>
        </div>
        <p v-if="quota < pending" class="note">今日配额不够全部生成，本次最多 {{ maxCount }} 条。</p>
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
import { cookieStatus } from '@/components/base/status'
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
    return { loading: false, running: false, status: null, count: 1 }
  },
  computed: {
    quota() { return (this.status && this.status.total_available_quota) || 0 },
    maxCount() { return Math.min(this.quota, this.pending) }
  },
  methods: {
    cookieStatus,
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
        const res = await api.video.generateBatch(this.projectId, this.count, true)
        const d = res.data || {}
        const lines = [`共 ${d.total_shots} 条：成功 ${d.success_count}，失败 ${d.failed_count}`]
        ;(d.results || []).forEach(r => lines.push(`${r.account_name}：成功 ${r.success_count}，失败 ${r.failed_count}`))
        this.$emit('update:visible', false)
        this.$emit('done', d)
        MessageBox.alert(lines.join('\n'), '生成结果', { confirmButtonText: '知道了', type: d.failed_count > 0 ? 'warning' : 'success' })
      } catch (e) {
        toastError(e, '批量生成失败')
      } finally {
        this.running = false
      }
    }
  }
}
</script>
