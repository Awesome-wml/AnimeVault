<template>
  <el-dialog append-to-body title="新建作品" :visible="visible" width="440px" @update:visible="$emit('update:visible', $event)" @closed="reset">
    <form class="new-project" novalidate @submit.prevent="submit">
      <FormField label="作品名" :error="error" required>
        <el-input ref="name" v-model.trim="name" maxlength="50" placeholder="如：暴雨演武场" />
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

export default {
  name: 'NewProjectDialog',
  props: {
    visible: Boolean
  },
  data() {
    return { genres: GENRES, name: '', genre: GENRES[0], error: '', saving: false }
  },
  watch: {
    visible(v) {
      if (v) this.$nextTick(() => this.$refs.name && this.$refs.name.focus())
    }
  },
  methods: {
    reset() {
      this.name = ''
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
        const res = await api.project.create({ name: this.name, genre: this.genre })
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
