<template>
  <el-dialog :title="isEdit ? '编辑草稿' : '新建版本草稿'" :visible="visible" width="640px" append-to-body
             :close-on-click-modal="false" @update:visible="v => $emit('update:visible', v)" @open="reset">
    <el-form ref="form" :model="form" :rules="rules" label-position="top" @submit.native.prevent>
      <div class="form-row">
        <el-form-item label="版本号" prop="version">
          <el-input v-model="form.version" placeholder="如 1.2.3" data-testid="release-version" />
        </el-form-item>
        <el-form-item label="渠道" prop="channel">
          <el-select v-model="form.channel" style="width: 100%" data-testid="release-channel">
            <el-option v-for="c in channels" :key="c.value" :label="c.label" :value="c.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="平台" prop="platform">
          <el-select v-model="form.platform" placeholder="请选择" style="width: 100%" data-testid="release-platform">
            <el-option v-for="p in platforms" :key="p.value" :label="p.label" :value="p.value" />
          </el-select>
        </el-form-item>
      </div>
      <el-form-item label="下载地址" prop="url">
        <el-input v-model="form.url" placeholder="https://..." data-testid="release-url" />
      </el-form-item>
      <el-form-item label="sha256" prop="sha256">
        <el-input v-model="form.sha256" placeholder="安装包的 64 位十六进制摘要" class="mono" data-testid="release-sha256" />
      </el-form-item>
      <div class="form-row">
        <el-form-item label="文件大小（字节）" prop="size">
          <el-input-number v-model="form.size" :min="1" :step="1048576" :controls="false" style="width: 100%"
                           data-testid="release-size" />
          <span class="note">{{ sizeText }}</span>
        </el-form-item>
        <el-form-item label="强制升级线（可选）" prop="min_supported">
          <el-input v-model="form.min_supported" placeholder="低于此版本的客户端被强制升级，如 1.0.0" data-testid="release-min" />
        </el-form-item>
      </div>
      <el-form-item label="更新说明（纯文本）" prop="notes">
        <el-input v-model="form.notes" type="textarea" :rows="5" :maxlength="maxNotes" show-word-limit
                  data-testid="release-notes" />
      </el-form-item>
    </el-form>
    <span slot="footer">
      <el-button @click="$emit('update:visible', false)">取消</el-button>
      <el-button type="primary" :loading="submitting" data-testid="release-submit" @click="submit">{{ isEdit ? '保存' : '创建草稿' }}</el-button>
    </span>
  </el-dialog>
</template>

<script>
import { api } from '@/api'
import { CHANNELS, MAX_NOTES, PLATFORMS } from '@/config/releases'
import { formatSize, releaseFormErrors, toForm, toPayload } from '@/utils/release'

const blank = () => ({ version: '', channel: 'stable', platform: '', notes: '', url: '', sha256: '', size: undefined, min_supported: '' })

/** 新建 / 编辑版本草稿。校验规则取自 utils/release.js，和服务端一致；服务端校验失败由拦截器提示。 */
export default {
  name: 'ReleaseFormDialog',
  props: {
    visible: { type: Boolean, default: false },
    /** 传入草稿则为编辑，不传为新建 */
    release: { type: Object, default: null }
  },
  data() {
    const field = key => ({
      validator: (rule, value, cb) => {
        const msg = releaseFormErrors(this.form)[key]
        msg ? cb(new Error(msg)) : cb()
      },
      trigger: 'blur'
    })
    const keys = ['version', 'channel', 'platform', 'url', 'sha256', 'size', 'min_supported', 'notes']
    return {
      form: blank(), submitting: false, channels: CHANNELS, platforms: PLATFORMS, maxNotes: MAX_NOTES,
      rules: keys.reduce((acc, k) => { acc[k] = [field(k)]; return acc }, {})
    }
  },
  computed: {
    isEdit() { return !!this.release },
    sizeText() { return this.form.size ? '≈ ' + formatSize(this.form.size) : '' }
  },
  methods: {
    reset() {
      this.form = this.release ? toForm(this.release) : blank()
      this.$nextTick(() => this.$refs.form && this.$refs.form.clearValidate())
    },
    async submit() {
      const valid = await this.$refs.form.validate().then(() => true, () => false)
      if (!valid) return
      this.submitting = true
      try {
        const payload = toPayload(this.form)
        const res = this.isEdit ? await api.releases.update(this.release.id, payload) : await api.releases.create(payload)
        this.$message.success(this.isEdit ? '草稿已保存' : '草稿已创建')
        this.$emit('update:visible', false)
        this.$emit('saved', res)
      } catch (e) {
        // 拦截器已提示；草稿已被别人发布 / 删除时通知页面刷新
        if (e.code === 'RELEASE_NOT_DRAFT' || e.code === 'RELEASE_NOT_FOUND') { this.$emit('update:visible', false); this.$emit('saved', null) }
      } finally {
        this.submitting = false
      }
    }
  }
}
</script>
