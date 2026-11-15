/**
 * 授权全局提示条的状态判断（纯函数，不依赖 Vue，便于单测）。
 * 入参是 /api/license/status 的返回；返回 null 表示不显示。
 *   level   'warning'（黄）| 'danger'（红）
 *   action  条上的按钮：'renew' 立即检查 | 'activate' 去重新激活
 *   dialog  true 时额外弹窗提示（session_conflict）
 */
import { formatDateTime } from './license.js'

export function bannerModel(status) {
  if (!status || !status.state) return null
  switch (status.state) {
    case 'grace':
      return {
        level: 'warning',
        text: `已离线使用，请在 ${formatDateTime(status.grace_until)} 前联网，否则将进入只读模式`,
        action: 'renew'
      }
    case 'expired':
      return { level: 'danger', text: '授权已到期，当前为只读模式，请联系我们续期', action: 'renew' }
    case 'suspended':
      return { level: 'danger', text: '授权已停用，当前为只读模式，请联系管理员', action: 'renew' }
    case 'lease_expired':
      return { level: 'danger', text: '离线时间过长，当前为只读模式，请联网后点击「立即检查」', action: 'renew' }
    case 'clock_rollback':
      return { level: 'danger', text: '检测到系统时间异常，请联网', action: 'renew' }
    case 'session_conflict':
      return {
        level: 'danger',
        text: '该授权已在另一台设备使用，本机已被下线',
        action: 'activate',
        dialog: true
      }
    default:
      return null
  }
}

export const SESSION_CONFLICT_DIALOG = {
  title: '授权已在另一台设备使用',
  message: '该授权已在另一台设备使用。重新激活会让对方下线。',
  confirm: '去重新激活',
  cancel: '稍后'
}

/** 是否需要弹出 session_conflict 弹窗：状态变成 session_conflict 且还没弹过 */
export function shouldShowDialog(model, alreadyShown) {
  return !!model && !!model.dialog && !alreadyShown
}
