/** 授权展示用的纯函数：套餐名、状态文案、到期时间（激活页、设置页、单测共用） */

const PLAN_LABELS = { trial: '试用版', basic: '基础版', pro: '专业版', ultimate: '旗舰版' }

export function planLabel(plan) {
  if (!plan) return '—'
  return PLAN_LABELS[plan] || plan
}

export const STATE_LABELS = {
  unactivated: '未激活',
  valid: '有效',
  grace: '离线使用中',
  lease_expired: '离线过久（只读）',
  expired: '已过期',
  suspended: '已停用（只读）',
  revoked: '已吊销',
  session_conflict: '已在另一台设备使用',
  clock_rollback: '系统时间异常',
  machine_mismatch: '授权码不是本机的',
  invalid: '无效'
}

export function stateLabel(state) {
  return STATE_LABELS[state] || '未知'
}

/** expires_at 为秒级时间戳；返回 2026-12-31 形式的本地日期 */
export function formatExpiry(expiresAt) {
  if (!expiresAt) return '—'
  const d = new Date(expiresAt * 1000)
  if (Number.isNaN(d.getTime())) return '—'
  const pad = n => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

/** 距到期还有多少整天（已过期返回负数或 0；无到期时间返回 null） */
export function daysLeft(expiresAt, nowMs = Date.now()) {
  if (!expiresAt) return null
  return Math.floor((expiresAt * 1000 - nowMs) / 86400000)
}

/** 秒级时间戳 -> 2026-12-31 08:05（本地时间）；空值返回 '—' */
export function formatDateTime(ts) {
  if (!ts) return '—'
  const d = new Date(ts * 1000)
  if (Number.isNaN(d.getTime())) return '—'
  const pad = n => String(n).padStart(2, '0')
  return `${formatExpiry(ts)} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}
