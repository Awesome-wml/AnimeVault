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
