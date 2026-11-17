/** 版本发布的纯函数：semver 比较、表单校验、状态机、展示文案。与服务端 services/releases.py、semver.py 保持一致。 */
import { CHANNELS, MAX_NOTES, PLATFORMS } from '../config/releases.js'

export const RELEASE_STATUS_META = {
  draft: { label: '草稿', tone: 'grey' },
  published: { label: '已发布', tone: 'green' },
  withdrawn: { label: '已撤回', tone: 'dark' }
}

export const RELEASE_STATUS_OPTIONS = Object.keys(RELEASE_STATUS_META).map(value => ({ value, label: RELEASE_STATUS_META[value].label }))

export function releaseStatusMeta(status) {
  return RELEASE_STATUS_META[status] || { label: status || '-', tone: 'grey' }
}

const SEMVER = /^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$/

export function isSemver(v) {
  return typeof v === 'string' && v.length <= 64 && SEMVER.test(v.trim())
}

function semverKey(v) {
  const m = SEMVER.exec(String(v).trim())
  if (!m) return null
  const pre = m[4] === undefined ? null : m[4].split('.').map(p => (/^\d+$/.test(p) ? [0, Number(p), ''] : [1, 0, p]))
  return { core: [Number(m[1]), Number(m[2]), Number(m[3])], pre }
}

function cmpArr(a, b) {
  for (let i = 0; i < Math.max(a.length, b.length); i++) {
    if (a[i] === undefined) return -1
    if (b[i] === undefined) return 1
    const x = Array.isArray(a[i]) ? cmpArr(a[i], b[i]) : (a[i] > b[i]) - (a[i] < b[i])
    if (x) return x
  }
  return 0
}

/** semver 比较（忽略 +构建信息；预发布低于同号正式版）。格式不合法返回 NaN。 */
export function compareSemver(a, b) {
  const ka = semverKey(a)
  const kb = semverKey(b)
  if (!ka || !kb) return NaN
  const c = cmpArr(ka.core, kb.core)
  if (c) return c
  if (!ka.pre && !kb.pre) return 0
  if (!ka.pre) return 1
  if (!kb.pre) return -1
  return cmpArr(ka.pre, kb.pre)
}

export function isDownloadUrl(v) {
  const s = typeof v === 'string' ? v.trim() : ''
  if (!s || s.length > 2048) return false
  let u
  try { u = new URL(s) } catch (e) { return false }
  if (u.username || u.password || !u.hostname) return false
  return u.protocol === 'https:' || (u.protocol === 'http:' && u.hostname === '127.0.0.1')
}

export const isSha256 = v => typeof v === 'string' && /^[0-9a-fA-F]{64}$/.test(v.trim())

export const isPositiveInt = v => Number.isInteger(v) && v >= 1 && v <= 2 ** 40

/** 逐字段校验，返回 {field: 文案}；全部合法返回空对象。 */
export function releaseFormErrors(f) {
  const e = {}
  if (!isSemver(f.version)) e.version = '版本号格式应为 x.y.z，可带 -预发布 与 +构建信息'
  if (!CHANNELS.some(c => c.value === f.channel)) e.channel = '请选择渠道'
  if (!PLATFORMS.some(p => p.value === f.platform)) e.platform = '请选择平台'
  if (!isDownloadUrl(f.url)) e.url = '下载地址必须是 https 地址（开发环境允许 http://127.0.0.1）'
  if (!isSha256(f.sha256)) e.sha256 = 'sha256 必须是 64 位十六进制'
  if (!isPositiveInt(f.size)) e.size = '文件大小必须是正整数（字节）'
  if ((f.notes || '').length > MAX_NOTES) e.notes = `更新说明不能超过 ${MAX_NOTES} 字`
  const ms = (f.min_supported || '').trim()
  if (ms) {
    if (!isSemver(ms)) e.min_supported = '强制升级线格式应为 x.y.z'
    else if (isSemver(f.version) && compareSemver(ms, f.version) > 0) e.min_supported = '强制升级线不能高于该版本自身的版本号'
  }
  return e
}

/** 表单 -> 提交给服务端的 payload（去空白、sha256 小写、空的强制升级线用 null）。 */
export function toPayload(f) {
  return {
    version: f.version.trim(),
    channel: f.channel,
    platform: f.platform,
    notes: (f.notes || '').trim(),
    url: f.url.trim(),
    sha256: f.sha256.trim().toLowerCase(),
    size: f.size,
    min_supported: (f.min_supported || '').trim() || null
  }
}

/** 记录 -> 表单初值。 */
export function toForm(r) {
  return {
    version: r.version, channel: r.channel, platform: r.platform, notes: r.notes || '', url: r.url,
    sha256: r.sha256, size: r.size, min_supported: r.min_supported || ''
  }
}

/** 状态机：草稿可编辑、发布；已发布可撤回；已撤回是终态。 */
export function releaseActions(status) {
  return { edit: status === 'draft', publish: status === 'draft', withdraw: status === 'published' }
}

export function releaseLabel(list, value) {
  const o = list.find(x => x.value === value)
  return o ? o.label : value || '-'
}

/** 字节数 -> 人类可读。 */
export function formatSize(bytes) {
  const n = Number(bytes)
  if (!Number.isFinite(n) || n < 0) return '-'
  if (n < 1024) return `${n} B`
  const units = ['KB', 'MB', 'GB', 'TB']
  let v = n
  let i = -1
  do { v /= 1024; i++ } while (v >= 1024 && i < units.length - 1)
  return `${v >= 100 ? v.toFixed(0) : v.toFixed(1)} ${units[i]}`
}

/** 发布 / 撤回成功后给管理员看的提示（服务端 warnings 原样展示）。 */
export function releaseNotice(res) {
  return (res && Array.isArray(res.warnings) ? res.warnings : []).filter(Boolean).join('；')
}
