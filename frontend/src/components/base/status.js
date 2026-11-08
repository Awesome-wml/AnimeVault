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
  // 分镜生成中（{n} 为进度百分比）
  shot_generating: { text: '生成中 {n}%', tone: 'warn' }
}

/** 登录有效期天数 → 状态 key */
export function cookieStatus(days) {
  if (days === null || days === undefined) return 'cookie_none'
  if (days <= 0) return 'cookie_expired'
  if (days < 7) return 'cookie_soon'
  if (days < 14) return 'cookie_warn'
  return 'cookie_ok'
}

export function statusInfo(key, n) {
  const s = STATUS[key] || { text: key, tone: 'muted' }
  return { text: s.text.replace('{n}', n === undefined ? '' : n), tone: s.tone }
}
