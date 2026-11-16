import { isBeforeToday } from './time.js'

export const MIN_PASSWORD_LEN = 12

/** 返回错误文案，合法返回空串。 */
export function passwordError(pw) {
  if (!pw) return '请输入密码'
  if (pw.length < MIN_PASSWORD_LEN) return `密码至少 ${MIN_PASSWORD_LEN} 位（当前 ${pw.length} 位）`
  return ''
}

export const USERNAME_PATTERN = /^[a-z0-9][a-z0-9_.-]{2,31}$/

export function usernameError(name) {
  const v = String(name || '').trim().toLowerCase()
  if (!v) return '请输入用户名'
  if (!USERNAME_PATTERN.test(v)) return '用户名 3-32 位，只能用小写字母、数字、点、下划线、短横线'
  return ''
}

/**
 * 授权条款（套餐、功能点、到期时间）的表单校验规则，签发和申请单签发共用。
 * @param {() => RegExp} getPattern 功能点格式（来自 /meta，取不到用兜底）
 */
export function licenseTermsRules(getPattern) {
  return {
    plan: [{ required: true, message: '请选择套餐', trigger: 'change' }],
    features: [{
      validator: (rule, value, cb) => {
        const bad = (value || []).filter(f => !getPattern().test(f))
        bad.length ? cb(new Error('功能点只能是小写字母、数字、下划线：' + bad.join('、'))) : cb()
      },
      trigger: 'change'
    }],
    expires: [{
      validator: (rule, value, cb) => {
        if (!value) return cb(new Error('请选择到期时间'))
        if (isBeforeToday(new Date(value))) return cb(new Error('到期时间不能早于今天'))
        cb()
      },
      trigger: 'change'
    }]
  }
}
