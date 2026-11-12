<template>
  <el-dialog append-to-body title="新建作品" :visible="visible" width="440px" @update:visible="$emit('update:visible', $event)" @closed="reset">
    <form class="new-project" novalidate @submit.prevent="submit">
      <FormField label="作品名" :error="error" required>
        <el-input ref="name" v-model.trim="name" maxlength="50" placeholder="如：暴雨演武场" />
      </FormField>
      <FormField label="画面类型" hint="决定角色、场景、分镜、视频的整体画风，默认真人实拍；创建后可在风格页修改">
        <el-select v-model="medium" placeholder="请选择画面类型">
          <el-option v-for="m in mediums" :key="m.id" :label="m.name" :value="m.id" />
        </el-select>
      </FormField>
      <FormField label="题材">
        <el-select v-model="genre">
          <el-option v-for="g in genres" :key="g" :label="g" :value="g" />
        </el-select>
      </FormField>
      <button type="submit" hidden></button>
    </form>
    <template #footer>
      <BaseButton variant="text" @click="$emit('update:visible', false)">取消</BaseButton>
      <BaseButton variant="primary" :loading="saving" @click="submit">创建并开始</BaseButton>
    </template>
  </el-dialog>
</template>

<script>
/** 新建作品对话框（首页、全部作品共用）。创建成功后进入该作品的小说页。 */
import { api } from '@/api'
import { GENRES } from './meta'
import { toastError } from '@/utils/notify'
import { loadStyleLibrary } from './styleLoader'

const FALLBACK_MEDIUM = 'realistic'
const BUILTIN_MEDIUMS = [
  { id: 'realistic', name: '真人实拍' },
  { id: 'cg3d', name: '3D 国漫' },
  { id: '2d_guoman', name: '2D 动漫 · 现代国漫' },
  { id: '2d_gufeng', name: '2D 动漫 · 古风厚涂' },
  { id: '2d_cel', name: '2D 动漫 · 日系赛璐璐' }
]

export default {
  name: 'NewProjectDialog',
  props: {
    visible: Boolean
  },
  data() {
    return { genres: GENRES, mediums: BUILTIN_MEDIUMS, medium: FALLBACK_MEDIUM, name: '', genre: GENRES[0], error: '', saving: false }
  },
  watch: {
    visible(v) {
      if (v) this.$nextTick(() => this.$refs.name && this.$refs.name.focus())
    }
  },
  created() {
    // 风格库就绪后用库里的媒介列表（含子风格全名）；失败时沿用内置列表，画面类型始终有默认值，不会为空
    loadStyleLibrary().then(lib => {
      if (lib.mediums && lib.mediums.length) {
        const group = id => (lib.medium_groups.find(g => g.id === id) || {}).name
        this.mediums = lib.mediums.map(m => ({ id: m.id, name: m.group === '2d' ? `${group('2d') || '2D 动漫'} · ${m.name}` : m.name }))
      }
    }, () => {})
  },
  methods: {
    reset() {
      this.name = ''
      this.medium = FALLBACK_MEDIUM
      this.genre = GENRES[0]
      this.error = ''
    },
    async submit() {
      if (!this.name) {
        this.error = '请输入作品名'
        return
      }
      this.saving = true
      try {
        const res = await api.project.create({ name: this.name, genre: this.genre, medium: this.medium || FALLBACK_MEDIUM })
        const id = res && res.data && res.data.id
        this.$emit('update:visible', false)
        this.$emit('created', id)
        if (id) this.$router.push(`/projects/${id}/novel`)
      } catch (e) {
        toastError(e)
      } finally {
        this.saving = false
      }
    }
  }
}
</script>

<style scoped>
.new-project { display: flex; flex-direction: column; gap: 16px; }
</style>
