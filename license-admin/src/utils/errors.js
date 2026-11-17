/** 后端 {code, message} -> 中文提示。纯函数，拦截器和单测共用。 */
export const ERROR_MESSAGES = {
  LOGIN_FAILED: '用户名或密码错误',
  LOGIN_LOCKED: '登录失败次数过多，账号已被临时锁定',
  FORBIDDEN: '没有权限执行此操作',
  UNAUTHENTICATED: '登录已失效，请重新登录',
  INVALID_TRANSITION: '授权当前状态不允许此操作，请刷新后重试',
  MACHINE_CODE_INVALID: '机器码无效，请检查是否复制完整、有无多余或缺失字符',
  MACHINE_CODE_TOO_FEW: '机器码有效硬件分量不足 2 个，为防止误绑已拒绝签发',
  EXPIRES_IN_PAST: '到期时间必须晚于当前时间',
  PLAN_INVALID: '套餐无效，请从列表中选择',
  FEATURE_INVALID: '功能点只能包含小写字母、数字和下划线',
  LAST_SUPER: '不能禁用或降级最后一个超级管理员',
  USERNAME_EXISTS: '用户名已存在',
  USERNAME_INVALID: '用户名需 3-32 位，只能用小写字母、数字、点、下划线、短横线，且以字母或数字开头',
  PASSWORD_TOO_SHORT: '密码至少 12 位',
  ROLE_INVALID: '角色不合法',
  NO_CHANGES: '没有要修改的内容',
  ADMIN_NOT_FOUND: '管理员不存在',
  LICENSE_NOT_FOUND: '授权不存在',
  LID_COLLISION: '授权 ID 冲突，请重试',
  NO_ACTIVE_SESSION: '该授权当前没有在线会话，无需踢下线',
  DEVICE_NOT_FOUND: '设备不存在，请刷新后重试',
  DEVICE_NOT_BOUND: '该设备已解绑，请刷新后重试',
  REQUEST_NOT_FOUND: '申请单不存在',
  REQUEST_NOT_PENDING: '该申请单已被处理，请刷新列表',
  EMAIL_INVALID: '邮箱格式不正确',
  STATUS_INVALID: '状态筛选条件不合法',
  RELEASE_NOT_FOUND: '版本记录不存在，请刷新列表',
  RELEASE_DUPLICATE: '该渠道和平台下已存在相同版本号',
  RELEASE_NOT_DRAFT: '只有草稿可以修改，请刷新后重试',
  VERSION_INVALID: '版本号格式应为 x.y.z，可带 -预发布 与 +构建信息',
  MIN_SUPPORTED_INVALID: '强制升级线格式应为 x.y.z',
  MIN_SUPPORTED_TOO_HIGH: '强制升级线不能高于该版本自身的版本号',
  CHANNEL_INVALID: '渠道只能是 stable 或 beta',
  PLATFORM_INVALID: '平台不合法，请从列表中选择',
  URL_INVALID: '下载地址必须是 https 地址（开发环境允许 http://127.0.0.1）',
  SHA256_INVALID: 'sha256 必须是 64 位十六进制',
  SIZE_INVALID: '文件大小必须是正整数（字节）',
  NOTES_INVALID: '更新说明过长',
  RATE_LIMITED: '请求过于频繁，请稍后再试',
  VALIDATION_ERROR: '提交的内容不合法，请检查后重试'
}

const STATUS_FALLBACK = {
  400: '请求不合法',
  401: '登录已失效，请重新登录',
  403: '没有权限执行此操作',
  404: '请求的内容不存在',
  409: '操作冲突，请刷新后重试',
  422: '提交的内容不合法',
  429: '请求过于频繁，请稍后再试'
}

/** 锁定剩余秒数 -> 「N 分钟」「N 秒」。 */
export function formatWait(seconds) {
  const s = Math.max(1, Math.ceil(Number(seconds) || 0))
  return s >= 60 ? `${Math.ceil(s / 60)} 分钟` : `${s} 秒`
}

/**
 * @param {{status?:number, data?:any, networkError?:boolean}} input
 * @returns {{code:string, message:string, status:number, retryAfter?:number}}
 */
export function mapError({ status = 0, data = null, networkError = false } = {}) {
  if (networkError) return { code: 'NETWORK_ERROR', message: '无法连接授权服务，请检查网络或服务是否已启动', status: 0 }
  const body = data && typeof data === 'object' ? data : {}
  const code = typeof body.code === 'string' ? body.code : ''
  if (code === 'LOGIN_LOCKED') {
    const retryAfter = Number(body.retry_after) || 0
    const wait = retryAfter ? `，请 ${formatWait(retryAfter)}后再试` : '，请稍后再试'
    return { code, message: ERROR_MESSAGES.LOGIN_LOCKED + wait, status, retryAfter }
  }
  if (code === 'VALIDATION_ERROR' && Array.isArray(body.fields) && body.fields.length) {
    return { code, message: `${ERROR_MESSAGES.VALIDATION_ERROR}（${body.fields.join('、')}）`, status }
  }
  if (code && ERROR_MESSAGES[code]) return { code, message: ERROR_MESSAGES[code], status }
  if (status >= 500) return { code: code || 'SERVER_ERROR', message: '授权服务内部错误，请稍后重试', status }
  // 未收录的 code：服务端的 message 是中文就直接用，否则按状态码兜底
  const msg = typeof body.message === 'string' && /[一-龥]/.test(body.message) ? body.message : ''
  return { code: code || 'UNKNOWN', message: msg || STATUS_FALLBACK[status] || '操作失败', status }
}
