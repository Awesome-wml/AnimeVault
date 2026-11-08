/**
 * 全站状态 → 文案 + 色调，唯一映射处。StatusText 读取这里。
 * tone：ok（墨绿）| warn（赭黄）| seal（印章红，失败/过期）| muted（灰）| ink（正文色）
 */
export const STATUS = {
  // 通用
  default: { text: '默认', tone: 'ink' },
  enabled: { text: '启用', tone: 'ok' },
  disabled: { text: '停用', tone: 'muted' },
  // 视频账号登录
  logged_in: { text: '已登录', tone: 'ok' },
  logged_out: { text: '未登录', tone: 'warn' },
  need_recheck: { text: '需重新检查', tone: 'warn' },
  // 登录有效期
  cookie_none: { text: '未保存', tone: 'muted' },
  cookie_expired: { text: '已过期', tone: 'seal' },
  cookie_soon: { text: '还有 {n} 天', tone: 'seal' },
  cookie_warn: { text: '还有 {n} 天', tone: 'warn' },
  cookie_ok: { text: '还有 {n} 天', tone: 'ink' },
  // 模型 Key
  key_none: { text: '复用全局', tone: 'muted' },
  key_some: { text: '{n} 个', tone: 'ink' },
  // 分镜（后端目前只能区分有无视频；审核/失败状态待后端支持）
  shot_no_video: { text: '待生成', tone: 'muted' },
  shot_has_video: { text: '已出视频', tone: 'ok' },
  shot_failed: { text: '失败', tone: 'seal' },
  shot_pending: { text: '待审核', tone: 'warn' },
  shot_approved: { text: '已通过', tone: 'ok' },
  // 列表行末的操作提示（首页“需要你处理”）
  action: { text: '', tone: 'muted' },
  action_alert: { text: '', tone: 'seal' },
  // 资产
  asset_no_image: { text: '缺参考图', tone: 'muted' },
  asset_has_image: { text: '已有图', tone: 'ok' },
  // 配音
  voice_done: { text: '已配音', tone: 'ok' },
  voice_none: { text: '未配音', tone: 'muted' },
  // 视频段填充率（台词朗读时长 / 段时长，{n} 为百分比；≥80% 为装满）
  fill_ok: { text: '填充 {n}%', tone: 'ok' },
  fill_mid: { text: '填充 {n}%', tone: 'warn' },
  fill_low: { text: '填充 {n}%', tone: 'seal' },
  // 分镜生成中（{n} 为进度百分比）
  shot_generating: { text: '生成中 {n}%', tone: 'warn' },
  // 视频账号额度（会员按豆包额度，非会员 / 读取失败按每日限额），由 quotaStatus 选择
  quota_member: { text: '{plan} · 已用 {used} / {total}', tone: 'ink' },
  quota_member_est: { text: '{plan} · 已用 {used} / {total} · 约可生成 {n} 条', tone: 'ink' },
  quota_exhausted: { text: '{plan} · 额度已用完', tone: 'seal' },
  quota_daily: { text: '今日 {used} / {limit}', tone: 'ink' },
  quota_daily_full: { text: '今日 {used} / {limit}', tone: 'seal' },
  quota_failed: { text: '额度读取失败，按每日 {limit} 条 · 今日 {used}', tone: 'warn' }
}

/** 登录有效期天数 → 状态 key */
export function cookieStatus(days) {
  if (days === null || days === undefined) return 'cookie_none'
  if (days <= 0) return 'cookie_expired'
  if (days < 7) return 'cookie_soon'
  if (days < 14) return 'cookie_warn'
  return 'cookie_ok'
}

/** 视频账号 → 登录状态 key（后端 login_status：logged_in | need_recheck | logged_out） */
export function loginStatus(account) {
  const s = account && account.login_status
  if (s && STATUS[s]) return s
  return account && account.logged_in ? 'logged_in' : 'logged_out'
}

/** 千分位数字：16100 → "16,100"；空值显示 "-" */
export function formatAmount(v) {
  if (v === null || v === undefined || v === '') return '-'
  const num = Number(v)
  return Number.isFinite(num) ? num.toLocaleString('en-US') : String(v)
}

/**
 * 视频账号 → 额度状态 { key, vars }，交给 StatusText（:status="key" :n="vars"）。
 * 账号字段来自 /api/video/accounts 或 /accounts/status：limit_mode、quota、remaining_estimate、today_used、daily_limit。
 */
export function quotaStatus(account, dailyLimit = 2) {
  const a = account || {}
  const q = a.quota
  const limit = a.daily_limit || dailyLimit
  const used = a.today_used || 0
  if (a.limit_mode === 'member' && q) {
    const vars = { plan: q.plan_name || '会员', used: formatAmount(q.used), total: formatAmount(q.total) }
    if (q.exhausted) return { key: 'quota_exhausted', vars }
    if (a.remaining_estimate !== null && a.remaining_estimate !== undefined) {
      return { key: 'quota_member_est', vars: { ...vars, n: a.remaining_estimate } }
    }
    return { key: 'quota_member', vars }
  }
  const vars = { used, limit }
  if (q && !q.ok) return { key: 'quota_failed', vars }
  return { key: used >= limit ? 'quota_daily_full' : 'quota_daily', vars }
}

/** 填充率（0~1）→ { key, n }：≥80% 装满，50%~80% 偏空，<50% 太空 */
export function fillStatus(rate) {
  const n = Math.round((Number(rate) || 0) * 100)
  return { key: n >= 80 ? 'fill_ok' : n >= 50 ? 'fill_mid' : 'fill_low', n }
}

/** n 可以是数字（替换 {n}），也可以是对象（按键替换 {plan} {used} 等） */
export function statusInfo(key, n) {
  const s = STATUS[key] || { text: key, tone: 'muted' }
  const vars = n !== null && typeof n === 'object' ? n : { n }
  const text = s.text.replace(/\{(\w+)\}/g, (_, k) => (vars[k] === undefined || vars[k] === null ? '' : vars[k]))
  return { text, tone: s.tone }
}
