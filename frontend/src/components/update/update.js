/**
 * 更新提示的纯函数（不依赖 Vue，便于单测）：提示条是否显示、强制升级页文案、「稍后」记忆、安装动作。
 * 入参 status 是 /api/update/status 的返回：
 *   { current_version, platform, channel, update_available, latest: {version, notes, url, sha256, size, published_at}|null,
 *     force, min_supported, update_required, required_message, checked_at, check_failed }
 */

export const DISMISS_KEY = 'dongai.update.dismissed'

/** 有可展示的新版本（latest 存在且 update_available） */
export function hasUpdate(status) {
  return !!status && status.update_available === true && !!status.latest && !!status.latest.version
}

/** 需要强制升级（全屏页） */
export function isUpdateRequiredStatus(status) {
  return !!status && status.update_required === true
}

/** 提示条模型；null 表示不显示。强制升级时由全屏页接管，不显示提示条；用户点过「稍后」的版本不再提示 */
export function updateBannerModel(status, dismissedVersion = '') {
  if (!hasUpdate(status) || isUpdateRequiredStatus(status)) return null
  const v = status.latest.version
  if (dismissedVersion && dismissedVersion === v) return null
  return { version: v, text: `发现新版本 ${v}（当前 ${status.current_version || '—'}）`, hasNotes: !!(status.latest.notes || '').trim() }
}

/** 强制升级页模型 */
export function requiredScreenModel(status) {
  if (!isUpdateRequiredStatus(status)) return null
  const latest = status.latest || null
  return {
    currentVersion: status.current_version || '—',
    minVersion: status.min_supported || (latest && latest.version) || '',
    latestVersion: latest ? latest.version : '',
    notes: latest ? (latest.notes || '') : '',
    message: status.required_message || '当前版本过低，请升级到新版本后继续使用',
    canDownload: !!(latest && latest.url)
  }
}

/** 「稍后」：记住被忽略的版本（localStorage 不可用时静默忽略，只影响本次） */
export function readDismissed(storage) {
  try { return (storage && storage.getItem(DISMISS_KEY)) || '' } catch (_) { return '' }
}

export function writeDismissed(storage, version) {
  try { if (storage) storage.setItem(DISMISS_KEY, version) } catch (_) { /* 无存储时只在本次生效 */ }
}

export function formatSize(bytes) {
  if (!Number.isFinite(bytes) || bytes <= 0) return ''
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

/** ISO 时间 -> 2026-11-01；解析失败返回空串 */
export function formatPublishedAt(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const pad = n => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

const DOWNLOAD_ERRORS = {
  SHA256_MISMATCH: '安装包校验失败，已删除，请稍后重试',
  BAD_URL: '更新地址不安全，已拒绝下载',
  NO_SHA256: '更新信息不完整，暂时无法下载',
  NO_UPDATE: '暂时没有可下载的更新',
  HTTP_ERROR: '下载失败，请稍后重试',
  NETWORK: '下载失败，请检查网络后重试',
  SIZE_MISMATCH: '安装包大小不符，已删除，请稍后重试',
  BUSY: '正在下载中，请稍候'
}

/**
 * 去更新：桌面外壳可用时走应用内下载（主进程下载、校验、打开安装包），否则在系统浏览器打开下载地址。
 * env = { desktop: window.dongaiDesktop, open: url => window.open(url, '_blank', 'noopener') }
 * 返回 { ok, message, mode: 'desktop'|'browser' }；绝不抛异常。
 */
export async function startUpdate(latest, env = {}) {
  const desktop = env.desktop
  if (desktop && typeof desktop.downloadUpdate === 'function') {
    try {
      const r = await desktop.downloadUpdate()
      if (r && r.ok) return { ok: true, mode: 'desktop', message: '安装包已下载并校验通过，请按提示完成安装（安装前先退出本应用）' }
      return { ok: false, mode: 'desktop', message: (r && (DOWNLOAD_ERRORS[r.code] || r.message)) || '下载失败，请稍后重试' }
    } catch (_) {
      return { ok: false, mode: 'desktop', message: '下载失败，请稍后重试' }
    }
  }
  if (latest && /^https:\/\//i.test(latest.url || '') && typeof env.open === 'function') {
    env.open(latest.url)
    return { ok: true, mode: 'browser', message: '已在浏览器中打开下载地址' }
  }
  return { ok: false, mode: 'browser', message: DOWNLOAD_ERRORS.NO_UPDATE }
}
