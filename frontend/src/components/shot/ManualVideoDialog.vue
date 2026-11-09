<template>
  <el-dialog :title="`补录视频 · 镜头 ${shot ? shot.shot_no : ''}`" :visible="visible" width="520px" :close-on-click-modal="false" @update:visible="v => $emit('update:visible', v)" @open="reset">
    <div class="form-stack">
      <el-radio-group v-model="mode" size="small">
        <el-radio-button label="file">上传本地文件</el-radio-button>
        <el-radio-button label="url">粘贴视频直链</el-radio-button>
      </el-radio-group>

      <FormField v-if="mode === 'file'" label="视频文件" hint="支持 MP4 / MOV / WebM / MKV">
        <div class="inline-actions">
          <BaseButton @click="$refs.picker.open()">选择文件</BaseButton>
          <span class="note">{{ file ? file.name : '还没有选择' }}</span>
        </div>
        <FilePicker ref="picker" accept="video/mp4,video/quicktime,video/webm,video/x-matroska,.mp4,.mov,.webm,.mkv" @select="f => (file = f)" />
      </FormField>

      <FormField v-else label="视频地址" hint="豆包视频直链（vdl.doubao.com）">
        <el-input v-model.trim="url" type="textarea" :autosize="{ minRows: 3, maxRows: 6 }" placeholder="https://" />
      </FormField>
    </div>
    <template #footer>
      <BaseButton @click="$emit('update:visible', false)">取消</BaseButton>
      <BaseButton variant="primary" :loading="submitting" :disabled="mode === 'file' ? !file : !url" @click="submit">
        {{ mode === 'file' ? '上传并绑定' : '下载并绑定' }}
      </BaseButton>
    </template>
  </el-dialog>
</template>

<script>
/** 给镜头手动补一段视频：上传文件或粘贴直链。成功 emit('done')。 */
import { api } from '@/api'
import { runAction } from '@/utils/notify'

export default {
  name: 'ManualVideoDialog',
  props: {
    visible: Boolean,
    shot: { type: Object, default: null }
  },
  data() {
    return { mode: 'file', file: null, url: '', submitting: false }
  },
  methods: {
    reset() {
      this.mode = 'file'
      this.file = null
      this.url = ''
    },
    async submit() {
      if (!this.shot) return
      this.submitting = true
      const ok = await runAction(
        () => (this.mode === 'file'
          ? api.video.uploadShotVideo(this.shot.id, this.file)
          : api.video.fetchShotVideoByUrl(this.shot.id, this.url)),
        { success: res => (res && res.message) || '视频已绑定', error: this.mode === 'file' ? '上传失败' : '下载失败' }
      )
      this.submitting = false
      if (ok) {
        this.$emit('update:visible', false)
        this.$emit('done')
      }
    }
  }
}
</script>
