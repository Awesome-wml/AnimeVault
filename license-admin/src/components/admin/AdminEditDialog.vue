<template>
  <el-dialog :title="mode === 'role' ? '修改角色' : '重置密码'" :visible="visible" width="440px" append-to-body
             :close-on-click-modal="false" @update:visible="v => $emit('update:visible', v)" @open="reset">
    <el-form v-if="admin" ref="form" :model="form" :rules="rules" label-position="top" @submit.native.prevent>
      <p class="note edit-target">管理员：<b>{{ admin.username }}</b></p>
      <el-form-item v-if="mode === 'role'" label="角色" prop="role">
        <el-select v-model="form.role" style="width: 100%" data-testid="edit-role">
          <el-option v-for="r in roles" :key="r.value" :label="r.label" :value="r.value" />
        </el-select>
      </el-form-item>
      <template v-else>
        <el-form-item label="新密码（至少 12 位）" prop="password">
          <el-input v-model="form.password" type="password" show-password autocomplete="new-password" data-testid="edit-password" />
        </el-form-item>
        <p class="note note--warn">重置后，该管理员已登录的会话会立即失效。</p>
      </template>
    </el-form>
    <span slot="footer">
      <el-button @click="$emit('update:visible', false)">取消</el-button>
      <el-button type="primary" :loading="loading" data-testid="edit-ok" @click="submit">保存</el-button>
    </span>
  </el-dialog>
</template>

<script>
import { api } from '@/api'
import { ROLES } from '@/config/roles'
import { passwordError } from '@/utils/validators'

export default {
  name: 'AdminEditDialog',
  props: {
    visible: { type: Boolean, default: false },
    mode: { type: String, default: 'role' }, // role | password
    admin: { type: Object, default: null }
  },
  data() {
    return {
      form: { role: '', password: '' }, loading: false, roles: ROLES,
      rules: { password: [{ validator: (r, v, cb) => { const m = passwordError(v); m ? cb(new Error(m)) : cb() }, trigger: 'blur' }] }
    }
  },
  methods: {
    reset() {
      this.form = { role: this.admin ? this.admin.role : '', password: '' }
      this.$nextTick(() => this.$refs.form && this.$refs.form.clearValidate())
    },
    async submit() {
      const ok = await this.$refs.form.validate().then(() => true, () => false)
      if (!ok) return
      this.loading = true
      try {
        const patch = this.mode === 'role' ? { role: this.form.role } : { password: this.form.password }
        await api.admins.update(this.admin.id, patch)
        this.$message.success(this.mode === 'role' ? '角色已修改' : '密码已重置')
        this.$emit('update:visible', false)
        this.$emit('saved')
      } catch (e) { /* 拦截器已提示 */ } finally {
        this.loading = false
      }
    }
  }
}
</script>

<style scoped>
.edit-target { margin-bottom: 12px; }
</style>
