<template>
  <el-dialog title="新建管理员" :visible="visible" width="460px" append-to-body :close-on-click-modal="false"
             @update:visible="v => $emit('update:visible', v)" @open="reset">
    <el-form ref="form" :model="form" :rules="rules" label-position="top" @submit.native.prevent>
      <el-form-item label="用户名" prop="username">
        <el-input v-model="form.username" placeholder="3-32 位小写字母、数字、._-" autocomplete="off" data-testid="admin-username" />
      </el-form-item>
      <el-form-item label="初始密码（至少 12 位）" prop="password">
        <el-input v-model="form.password" type="password" show-password autocomplete="new-password" data-testid="admin-password" />
      </el-form-item>
      <el-form-item label="角色" prop="role">
        <el-select v-model="form.role" style="width: 100%" data-testid="admin-role">
          <el-option v-for="r in roles" :key="r.value" :label="r.label" :value="r.value" />
        </el-select>
      </el-form-item>
    </el-form>
    <span slot="footer">
      <el-button @click="$emit('update:visible', false)">取消</el-button>
      <el-button type="primary" :loading="loading" data-testid="admin-create-ok" @click="submit">创建</el-button>
    </span>
  </el-dialog>
</template>

<script>
import { api } from '@/api'
import { ROLES } from '@/config/roles'
import { passwordError, usernameError } from '@/utils/validators'

export default {
  name: 'AdminCreateDialog',
  props: { visible: { type: Boolean, default: false } },
  data() {
    const wrap = fn => (rule, v, cb) => { const m = fn(v); m ? cb(new Error(m)) : cb() }
    return {
      form: { username: '', password: '', role: 'ops' }, loading: false, roles: ROLES,
      rules: {
        username: [{ validator: wrap(usernameError), trigger: 'blur' }],
        password: [{ validator: wrap(passwordError), trigger: 'blur' }]
      }
    }
  },
  methods: {
    reset() {
      this.form = { username: '', password: '', role: 'ops' }
      this.$nextTick(() => this.$refs.form && this.$refs.form.clearValidate())
    },
    async submit() {
      const ok = await this.$refs.form.validate().then(() => true, () => false)
      if (!ok) return
      this.loading = true
      try {
        await api.admins.create({ username: this.form.username.trim().toLowerCase(), password: this.form.password, role: this.form.role })
        this.$message.success('管理员已创建')
        this.$emit('update:visible', false)
        this.$emit('saved')
      } catch (e) { /* 拦截器已提示 */ } finally {
        this.loading = false
      }
    }
  }
}
</script>
