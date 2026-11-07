<template>
  <div class="login-container">
    <el-card class="login-card">
      <div slot="header" class="card-header">
        <h2>DongAI 短剧工作台</h2>
        <p>AI驱动的短剧创作平台</p>
      </div>
      
      <el-tabs v-model="activeTab" @tab-click="handleTabClick">
        <!-- 登录 -->
        <el-tab-pane label="登录" name="login">
          <el-form ref="loginForm" :model="loginForm" :rules="loginRules" label-width="80px">
            <el-form-item label="用户名" prop="username">
              <el-input v-model="loginForm.username" placeholder="请输入用户名"></el-input>
            </el-form-item>
            <el-form-item label="密码" prop="password">
              <el-input v-model="loginForm.password" type="password" placeholder="请输入密码" @keyup.enter.native="handleLogin"></el-input>
            </el-form-item>
            <el-form-item>
              <el-button type="primary" :loading="loading" @click="handleLogin" style="width: 100%">登录</el-button>
            </el-form-item>
          </el-form>
        </el-tab-pane>
        
        <!-- 注册 -->
        <el-tab-pane label="注册" name="register">
          <el-form ref="registerForm" :model="registerForm" :rules="registerRules" label-width="80px">
            <el-form-item label="用户名" prop="username">
              <el-input v-model="registerForm.username" placeholder="请输入用户名（3-50字符）"></el-input>
            </el-form-item>
            <el-form-item label="密码" prop="password">
              <el-input v-model="registerForm.password" type="password" placeholder="请输入密码（至少6位）"></el-input>
            </el-form-item>
            <el-form-item label="确认密码" prop="confirmPassword">
              <el-input v-model="registerForm.confirmPassword" type="password" placeholder="请再次输入密码" @keyup.enter.native="handleRegister"></el-input>
            </el-form-item>
            <el-form-item>
              <el-button type="success" :loading="loading" @click="handleRegister" style="width: 100%">注册</el-button>
            </el-form-item>
          </el-form>
        </el-tab-pane>
      </el-tabs>
    </el-card>
  </div>
</template>

<script>
import { api } from '@/api'

export default {
  name: 'Login',
  data() {
    const validateConfirmPassword = (rule, value, callback) => {
      if (value !== this.registerForm.password) {
        callback(new Error('两次输入的密码不一致'))
      } else {
        callback()
      }
    }
    
    return {
      activeTab: 'login',
      loading: false,
      loginForm: {
        username: '',
        password: ''
      },
      registerForm: {
        username: '',
        password: '',
        confirmPassword: ''
      },
      loginRules: {
        username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
        password: [{ required: true, message: '请输入密码', trigger: 'blur' }]
      },
      registerRules: {
        username: [
          { required: true, message: '请输入用户名', trigger: 'blur' },
          { min: 3, max: 50, message: '用户名长度在3-50字符之间', trigger: 'blur' }
        ],
        password: [
          { required: true, message: '请输入密码', trigger: 'blur' },
          { min: 6, message: '密码至少6位', trigger: 'blur' }
        ],
        confirmPassword: [
          { required: true, message: '请再次输入密码', trigger: 'blur' },
          { validator: validateConfirmPassword, trigger: 'blur' }
        ]
      }
    }
  },
  methods: {
    handleTabClick() {
      this.$refs.loginForm && this.$refs.loginForm.clearValidate()
      this.$refs.registerForm && this.$refs.registerForm.clearValidate()
    },
    
    async handleLogin() {
      this.$refs.loginForm.validate(async valid => {
        if (!valid) return
        
        this.loading = true
        try {
          const res = await api.auth.login(this.loginForm)
          localStorage.setItem('token', res.data.token)
          this.$store.dispatch('setUser', res.data.user)
          this.$message.success('登录成功')
          this.$router.push('/dashboard')
        } catch (error) {
          console.error('登录失败:', error)
        } finally {
          this.loading = false
        }
      })
    },
    
    async handleRegister() {
      this.$refs.registerForm.validate(async valid => {
        if (!valid) return
        
        this.loading = true
        try {
          const res = await api.auth.register({
            username: this.registerForm.username,
            password: this.registerForm.password
          })
          localStorage.setItem('token', res.data.token)
          this.$store.dispatch('setUser', res.data.user)
          this.$message.success('注册成功')
          this.$router.push('/dashboard')
        } catch (error) {
          console.error('注册失败:', error)
        } finally {
          this.loading = false
        }
      })
    }
  }
}
</script>

<style scoped>
.login-container {
  display: flex;
  justify-content: center;
  align-items: center;
  min-height: 100vh;
  background: var(--primary-gradient);
  padding: 20px;
  position: relative;
  overflow: hidden;
}

.login-container::before {
  content: '';
  position: absolute;
  top: -50%;
  right: -20%;
  width: 600px;
  height: 600px;
  background: radial-gradient(circle, rgba(255, 255, 255, 0.1) 0%, transparent 70%);
  border-radius: 50%;
  animation: float 8s ease-in-out infinite;
}

.login-container::after {
  content: '';
  position: absolute;
  bottom: -30%;
  left: -10%;
  width: 500px;
  height: 500px;
  background: radial-gradient(circle, rgba(255, 255, 255, 0.08) 0%, transparent 70%);
  border-radius: 50%;
  animation: float 10s ease-in-out infinite reverse;
}

@keyframes float {
  0%, 100% { transform: translate(0, 0); }
  50% { transform: translate(30px, -30px); }
}

.login-card {
  width: 100%;
  max-width: 450px;
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-xl);
  overflow: hidden;
  position: relative;
  z-index: 1;
  border: none;
}

.login-card >>> .el-card__header {
  background: var(--bg-white);
  border-bottom: 1px solid var(--border-color);
  padding: 32px 32px 24px;
}

.login-card >>> .el-card__body {
  padding: 32px;
}

.card-header {
  text-align: center;
}

.card-header h2 {
  margin: 0 0 8px 0;
  font-size: 28px;
  font-weight: 700;
  background: var(--primary-gradient);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}

.card-header p {
  margin: 0;
  color: var(--text-secondary);
  font-size: 14px;
}

.login-card >>> .el-tabs__nav-wrap::after {
  display: none;
}

.login-card >>> .el-tabs__active-bar {
  background: var(--primary-gradient);
}

.login-card >>> .el-tabs__item {
  font-size: 15px;
  font-weight: 500;
  padding: 0 24px;
}

.login-card >>> .el-tabs__item.is-active {
  color: var(--primary);
}

.login-card >>> .el-button--primary {
  height: 44px;
  font-size: 15px;
  font-weight: 500;
  border-radius: var(--radius);
}

.login-card >>> .el-input__inner {
  height: 44px;
  border-radius: var(--radius);
  font-size: 14px;
}

.login-card >>> .el-form-item {
  margin-bottom: 22px;
}

.login-card >>> .el-form-item__label {
  font-weight: 500;
  color: var(--text-primary);
}
</style>
