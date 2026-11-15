<template>
  <div>
    <el-dialog title="延期授权" :visible.sync="extendVisible" width="460px" append-to-body :close-on-click-modal="false">
      <div class="form-stack">
        <WarnBar>延期会重新签发授权码，旧码作废。请把新的授权码发给用户。</WarnBar>
        <el-form label-position="top" @submit.native.prevent>
          <el-form-item :label="`新的到期时间（当前：${currentExpires}）`">
            <el-date-picker v-model="newExpires" type="date" placeholder="选择日期" value-format="timestamp"
                            :picker-options="pickerOptions" style="width: 100%" data-testid="extend-date" />
          </el-form-item>
        </el-form>
      </div>
      <span slot="footer">
        <el-button @click="extendVisible = false">取消</el-button>
        <el-button type="primary" :loading="loading" :disabled="!newExpires" data-testid="extend-ok" @click="doExtend">确认延期</el-button>
      </span>
    </el-dialog>

    <ConfirmDialog :visible.sync="confirmVisible" :title="confirm.title" :message="confirm.message"
                   :danger="confirm.danger" :require-text="confirm.requireText" :confirm-label="confirm.label"
                   :loading="loading" @confirm="doConfirm" />
  </div>
</template>

<script>
/**
 * 授权操作的对话框与调用都在这里：延期（选日期）、停用、恢复、吊销（输入 lid 二次确认）。
 * 列表页和详情抽屉只发 start(action, lic)，成功后收到 done(updatedLicense, action)。
 */
import { api } from '@/api'
import { endOfDaySeconds, formatTime, isBeforeToday } from '@/utils/time'

export default {
  name: 'LicenseActionHost',
  data() {
    return {
      lic: null, action: '', loading: false,
      extendVisible: false, newExpires: null,
      confirmVisible: false,
      confirm: { title: '', message: '', danger: false, requireText: '', label: '确认' },
      pickerOptions: { disabledDate: d => isBeforeToday(d) }
    }
  },
  computed: {
    currentExpires() { return this.lic ? formatTime(this.lic.expires_at, false) : '' }
  },
  methods: {
    start(action, lic) {
      this.lic = lic
      this.action = action
      if (action === 'extend') {
        this.newExpires = null
        this.extendVisible = true
        return
      }
      const text = {
        suspend: { title: '停用授权', message: `停用后客户端续租会被拒绝，可以随时恢复。确认停用 ${lic.lid}？`, label: '确认停用', danger: false },
        resume: { title: '恢复授权', message: `确认恢复 ${lic.lid}？`, label: '确认恢复', danger: false },
        revoke: { title: '吊销授权', message: `吊销后授权码永久失效，不可恢复。`, label: '确认吊销', danger: true }
      }[action]
      this.confirm = { ...text, requireText: action === 'revoke' ? lic.lid : '' }
      this.confirmVisible = true
    },
    async doExtend() {
      const exp = endOfDaySeconds(new Date(this.newExpires))
      await this.call(() => api.licenses.extend(this.lic.lid, exp), () => { this.extendVisible = false }, '已延期，授权码已重新签发')
    },
    async doConfirm() {
      const fn = api.licenses[this.action]
      const done = { suspend: '已停用', resume: '已恢复', revoke: '已吊销' }[this.action]
      await this.call(() => fn(this.lic.lid), () => { this.confirmVisible = false }, done)
    },
    async call(fn, close, okText) {
      this.loading = true
      try {
        const updated = await fn()
        close()
        this.$message.success(okText)
        this.$emit('done', updated, this.action)
      } catch (e) {
        // 拦截器已提示；状态冲突时通知页面刷新
        if (e.code === 'INVALID_TRANSITION') { close(); this.$emit('done', null, this.action) }
      } finally {
        this.loading = false
      }
    }
  }
}
</script>
