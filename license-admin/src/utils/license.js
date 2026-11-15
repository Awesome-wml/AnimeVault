/** 授权状态、状态机按钮可用性、到期判断。与服务端 services/licenses.py 的状态机一致。 */
export const STATUS_META = {
  pending: { label: '待激活', tone: 'grey' },
  active: { label: '正常', tone: 'green' },
  suspended: { label: '已停用', tone: 'orange' },
  revoked: { label: '已吊销', tone: 'red' },
  expired: { label: '已到期', tone: 'dark' }
}

export const STATUS_OPTIONS = Object.keys(STATUS_META).map(value => ({ value, label: STATUS_META[value].label }))

export function statusMeta(status) {
  return STATUS_META[status] || { label: status || '-', tone: 'grey' }
}

/** 每个状态允许的操作。revoked 全部不可用。 */
const ALLOWED = {
  pending: ['extend', 'revoke'],
  active: ['extend', 'suspend', 'revoke'],
  suspended: ['extend', 'resume', 'revoke'],
  expired: ['extend', 'revoke'],
  revoked: []
}

export const ACTIONS = ['extend', 'suspend', 'resume', 'revoke']

export function availableActions(status) {
  const allowed = ALLOWED[status] || []
  return ACTIONS.reduce((acc, a) => { acc[a] = allowed.includes(a); return acc }, {})
}

/** 不可用时给按钮的提示。 */
export function disabledReason(status, action) {
  if (availableActions(status)[action]) return ''
  if (status === 'revoked') return '授权已吊销，不可再操作'
  if (action === 'suspend') return status === 'pending' ? '待激活的授权不能停用' : '只有正常状态的授权可以停用'
  if (action === 'resume') return '只有已停用的授权可以恢复'
  return '当前状态不允许此操作'
}

export const DAY = 86400
export const SOON_DAYS = 7

/**
 * 到期提示级别：expired（已过期）/ soon（7 天内到期）/ normal。
 * 已吊销、已到期的授权不再提示临近。
 */
export function expiryLevel(expiresAt, status, nowSec = Math.floor(Date.now() / 1000)) {
  if (!expiresAt || status === 'revoked') return 'normal'
  if (expiresAt <= nowSec) return 'expired'
  if (status === 'expired') return 'normal'
  return expiresAt - nowSec <= SOON_DAYS * DAY ? 'soon' : 'normal'
}

/** 最近在线文案：从未激活显示「未激活」，激活过但无心跳显示「从未在线」。 */
export function lastSeenText(lic, format) {
  if (lic && lic.last_seen_at) return format(lic.last_seen_at)
  return lic && lic.status === 'pending' ? '未激活' : '从未在线'
}

export const EVENT_LABELS = {
  issued: '签发',
  extended: '延期（已重新签发授权码）',
  suspended: '停用',
  resumed: '恢复',
  revoked: '吊销',
  activated: '用户激活',
  expired: '到期'
}

export function eventLabel(type) {
  return EVENT_LABELS[type] || type
}

export const AUDIT_ACTIONS = [
  'license.issue', 'license.extend', 'license.suspend', 'license.resume', 'license.revoke', 'license.expire',
  'admin.create', 'admin.update',
  'auth.login_success', 'auth.login_failed', 'auth.login_locked'
]

export const AUDIT_ACTION_LABELS = {
  'license.issue': '签发授权',
  'license.extend': '延期授权',
  'license.suspend': '停用授权',
  'license.resume': '恢复授权',
  'license.revoke': '吊销授权',
  'license.expire': '授权到期',
  'admin.create': '新建管理员',
  'admin.update': '修改管理员',
  'auth.login_success': '登录成功',
  'auth.login_failed': '登录失败',
  'auth.login_locked': '登录锁定'
}

/** 事件时间线里的一行摘要。 */
export function eventSummary(ev, format = String) {
  const d = (ev && ev.detail) || {}
  if (ev.type === 'extended') return `到期时间 ${format(d.old_expires_at)} → ${format(d.new_expires_at)}`
  if (ev.type === 'issued') return `套餐 ${d.plan || '-'}，到期 ${format(d.expires_at)}`
  if (d.from && d.to) return `${statusMeta(d.from).label} → ${statusMeta(d.to).label}`
  return ''
}
