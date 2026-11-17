'use strict'
// 应用内下载更新包的纯逻辑（不依赖 electron，node --test 可直接测）：
//   - 地址策略：只允许 https；开发/测试构建（allowLoopbackHttp）额外允许 http://127.0.0.1 / localhost；
//   - 下载到 destDir，边下边算 sha256，和更新源给的 sha256 不一致就删除文件并报错（不留半成品、不打开）；
//   - 重定向逐跳按同一策略检查（https 不能被降级到 http，除本机地址的开发场景）。
// 真正的安装由用户手动完成（打开 dmg / 在文件夹中显示安装包），见 main.js 的 IPC 与 docs/versioning.md。
const crypto = require('crypto')
const fs = require('fs')
const http = require('http')
const https = require('https')
const path = require('path')

const MAX_REDIRECTS = 5
const SHA256_RE = /^[0-9a-f]{64}$/i
const LOOPBACK = new Set(['127.0.0.1', 'localhost', '[::1]', '::1'])

class UpdateDownloadError extends Error {
  constructor(code, message) {
    super(message)
    this.name = 'UpdateDownloadError'
    this.code = code
  }
}

/** 下载地址是否允许：https；allowLoopbackHttp 时额外允许本机 http */
function isAllowedDownloadUrl(u, { allowLoopbackHttp = false } = {}) {
  let p
  try { p = new URL(u) } catch (_) { return false }
  if (p.username || p.password) return false
  if (p.protocol === 'https:') return !!p.hostname
  if (p.protocol === 'http:') return !!allowLoopbackHttp && LOOPBACK.has(p.hostname)
  return false
}

/** 从 URL 取一个安全的本地文件名（只留字母数字 . _ -，不含路径分隔符） */
function safeFileName(u, fallback = 'DongAI-update.bin') {
  let base = ''
  try { base = path.posix.basename(decodeURIComponent(new URL(u).pathname)) } catch (_) { /* 用兜底 */ }
  base = base.replace(/[^A-Za-z0-9._-]/g, '_').replace(/^\.+/, '')
  return base || fallback
}

/** 安装包落地后的动作：dmg 直接打开（挂载），其余在文件夹中显示，由用户手动安装 */
function postDownloadAction(file) {
  return path.extname(file).toLowerCase() === '.dmg' ? 'open' : 'reveal'
}

function sha256File(file) {
  return new Promise((resolve, reject) => {
    const h = crypto.createHash('sha256')
    fs.createReadStream(file).on('error', reject).on('data', c => h.update(c)).on('end', () => resolve(h.digest('hex')))
  })
}

function defaultGet(u, cb) {
  const mod = u.startsWith('https:') ? https : http
  return mod.get(u, { headers: { 'User-Agent': 'DongAI-Updater' } }, cb)
}

/**
 * 下载并校验。opts：
 *   url, sha256（必填，64 位十六进制）, destDir, fileName?, expectedSize?, allowLoopbackHttp?, onProgress?({received,total}), get?（测试注入）
 * 成功返回 { file, sha256, size }；失败抛 UpdateDownloadError（code：BAD_URL / NO_SHA256 / HTTP_ERROR / SIZE_MISMATCH / SHA256_MISMATCH / NETWORK / TOO_MANY_REDIRECTS），
 * 且不会留下任何文件（含 .part）。
 */
async function downloadUpdate(opts) {
  const { url, sha256, destDir, expectedSize, allowLoopbackHttp = false, onProgress, get = defaultGet } = opts
  if (!isAllowedDownloadUrl(url, { allowLoopbackHttp })) throw new UpdateDownloadError('BAD_URL', '更新地址不安全，只允许 https')
  if (typeof sha256 !== 'string' || !SHA256_RE.test(sha256)) throw new UpdateDownloadError('NO_SHA256', '更新信息缺少校验值，无法安全下载')
  const want = sha256.toLowerCase()
  fs.mkdirSync(destDir, { recursive: true })
  const name = opts.fileName || safeFileName(url)
  const target = path.join(destDir, name)
  const part = target + '.part'
  const cleanup = () => { for (const f of [part]) { try { fs.unlinkSync(f) } catch (_) { /* 不存在 */ } } }

  try {
    const { size, hash } = await fetchToFile(url, part, { allowLoopbackHttp, onProgress, get })
    if (expectedSize != null && size !== expectedSize) throw new UpdateDownloadError('SIZE_MISMATCH', `文件大小不符（${size} / ${expectedSize}）`)
    if (hash !== want) throw new UpdateDownloadError('SHA256_MISMATCH', '安装包校验失败（sha256 不一致），已删除，请重试或联系我们')
    try { fs.unlinkSync(target) } catch (_) { /* 旧文件不存在 */ }
    fs.renameSync(part, target)
    return { file: target, sha256: hash, size }
  } catch (e) {
    cleanup()
    if (e instanceof UpdateDownloadError) throw e
    throw new UpdateDownloadError('NETWORK', `下载失败：${e && e.message ? e.message : e}`)
  }
}

function fetchToFile(url, dest, { allowLoopbackHttp, onProgress, get }, hops = 0) {
  return new Promise((resolve, reject) => {
    if (hops > MAX_REDIRECTS) return reject(new UpdateDownloadError('TOO_MANY_REDIRECTS', '重定向次数过多'))
    const req = get(url, res => {
      const status = res.statusCode || 0
      if ([301, 302, 303, 307, 308].includes(status) && res.headers.location) {
        res.resume()
        let next
        try { next = new URL(res.headers.location, url).toString() } catch (_) { return reject(new UpdateDownloadError('BAD_URL', '重定向地址无效')) }
        if (!isAllowedDownloadUrl(next, { allowLoopbackHttp })) return reject(new UpdateDownloadError('BAD_URL', '重定向到了不安全的地址'))
        return fetchToFile(next, dest, { allowLoopbackHttp, onProgress, get }, hops + 1).then(resolve, reject)
      }
      if (status !== 200) {
        res.resume()
        return reject(new UpdateDownloadError('HTTP_ERROR', `下载失败（HTTP ${status}）`))
      }
      const total = Number(res.headers['content-length']) || 0
      const hash = crypto.createHash('sha256')
      const out = fs.createWriteStream(dest)
      let received = 0
      res.on('data', chunk => {
        hash.update(chunk)
        received += chunk.length
        if (onProgress) onProgress({ received, total })
      })
      res.on('error', err => { out.destroy(); reject(err) })
      out.on('error', reject)
      out.on('finish', () => resolve({ size: received, hash: hash.digest('hex') }))
      res.pipe(out)
    })
    if (req && typeof req.on === 'function') req.on('error', reject)
  })
}

module.exports = { downloadUpdate, isAllowedDownloadUrl, safeFileName, postDownloadAction, sha256File, UpdateDownloadError }
