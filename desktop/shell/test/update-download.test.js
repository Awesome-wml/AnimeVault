'use strict'
const test = require('node:test')
const assert = require('node:assert/strict')
const crypto = require('crypto')
const fs = require('fs')
const http = require('http')
const os = require('os')
const path = require('path')
const { PassThrough } = require('stream')

const { downloadUpdate, isAllowedDownloadUrl, safeFileName, postDownloadAction, UpdateDownloadError } = require('../src/update-download')
const { checkVersions } = require('../scripts/check-version')

const tmp = () => fs.mkdtempSync(path.join(os.tmpdir(), 'dongai-upd-'))
const sha = buf => crypto.createHash('sha256').update(buf).digest('hex')

/** 假的 get：按 URL 返回预设响应（不碰网络） */
function fakeGet(routes) {
  return (url, cb) => {
    const r = routes[url]
    const res = new PassThrough()
    res.statusCode = r.status || 200
    res.headers = r.headers || {}
    setImmediate(() => {
      cb(res)
      if (r.body !== undefined) res.end(r.body)
      else res.end()
    })
    return { on() {} }
  }
}

test('地址策略：只允许 https；本机 http 仅开发/测试构建允许', () => {
  assert.equal(isAllowedDownloadUrl('https://dl.example.com/a.dmg'), true)
  assert.equal(isAllowedDownloadUrl('http://dl.example.com/a.dmg'), false)
  assert.equal(isAllowedDownloadUrl('http://127.0.0.1:9000/a.dmg'), false)
  assert.equal(isAllowedDownloadUrl('http://127.0.0.1:9000/a.dmg', { allowLoopbackHttp: true }), true)
  assert.equal(isAllowedDownloadUrl('http://localhost/a.dmg', { allowLoopbackHttp: true }), true)
  assert.equal(isAllowedDownloadUrl('http://evil.com/a.dmg', { allowLoopbackHttp: true }), false)
  assert.equal(isAllowedDownloadUrl('http://127.0.0.1.evil.com/a', { allowLoopbackHttp: true }), false)
  assert.equal(isAllowedDownloadUrl('file:///etc/passwd'), false)
  assert.equal(isAllowedDownloadUrl('ftp://x/y'), false)
  assert.equal(isAllowedDownloadUrl('https://u:p@dl.example.com/a'), false)
  assert.equal(isAllowedDownloadUrl('javascript:alert(1)'), false)
  assert.equal(isAllowedDownloadUrl(''), false)
  assert.equal(isAllowedDownloadUrl(null), false)
})

test('文件名清洗与安装后动作', () => {
  assert.equal(safeFileName('https://x.com/dl/DongAI-0.2.0-arm64.dmg?sig=1'), 'DongAI-0.2.0-arm64.dmg')
  assert.equal(safeFileName('https://x.com/dl/..%2F..%2Fetc%2Fpasswd'), 'passwd')
  assert.equal(safeFileName('https://x.com/'), 'DongAI-update.bin')
  assert.equal(postDownloadAction('/a/b/DongAI.dmg'), 'open')
  assert.equal(postDownloadAction('C:\\a\\DongAI-Setup.exe'), 'reveal')
})

test('sha256 一致：落盘、无 .part 残留，进度回调', async () => {
  const body = Buffer.from('hello-installer')
  const dir = tmp()
  const url = 'https://dl.example.com/DongAI.dmg'
  const seen = []
  const r = await downloadUpdate({
    url, sha256: sha(body), destDir: dir, expectedSize: body.length,
    onProgress: p => seen.push(p), get: fakeGet({ [url]: { body, headers: { 'content-length': String(body.length) } } })
  })
  assert.equal(path.basename(r.file), 'DongAI.dmg')
  assert.deepEqual(fs.readFileSync(r.file), body)
  assert.deepEqual(fs.readdirSync(dir), ['DongAI.dmg'])
  assert.ok(seen.length >= 1 && seen[seen.length - 1].received === body.length)
})

test('sha256 不符：拒绝并删除文件', async () => {
  const dir = tmp()
  const url = 'https://dl.example.com/DongAI.dmg'
  await assert.rejects(
    downloadUpdate({ url, sha256: sha(Buffer.from('other')), destDir: dir, get: fakeGet({ [url]: { body: 'tampered' } }) }),
    e => e instanceof UpdateDownloadError && e.code === 'SHA256_MISMATCH'
  )
  assert.deepEqual(fs.readdirSync(dir), [])
})

test('sha256 大小写不敏感；缺失或格式错误被拒（不发请求）', async () => {
  const body = Buffer.from('x')
  const url = 'https://dl.example.com/a.exe'
  const dir = tmp()
  const ok = await downloadUpdate({ url, sha256: sha(body).toUpperCase(), destDir: dir, get: fakeGet({ [url]: { body } }) })
  assert.ok(fs.existsSync(ok.file))
  let called = false
  const get = () => { called = true; throw new Error('不该发请求') }
  for (const bad of [undefined, '', 'abc', 'z'.repeat(64)]) {
    await assert.rejects(downloadUpdate({ url, sha256: bad, destDir: tmp(), get }), e => e.code === 'NO_SHA256')
  }
  assert.equal(called, false)
})

test('非 https 被拒（不发请求）；本机 http 仅在 allowLoopbackHttp 时放行', async () => {
  let called = false
  const get = () => { called = true; throw new Error('不该发请求') }
  const h = sha(Buffer.from('a'))
  await assert.rejects(downloadUpdate({ url: 'http://dl.example.com/a.dmg', sha256: h, destDir: tmp(), get }), e => e.code === 'BAD_URL')
  await assert.rejects(downloadUpdate({ url: 'http://127.0.0.1:1/a.dmg', sha256: h, destDir: tmp(), get }), e => e.code === 'BAD_URL')
  assert.equal(called, false)
})

test('重定向：https→http 被拒；https→https 跟随', async () => {
  const body = Buffer.from('payload')
  const a = 'https://dl.example.com/a.dmg'
  await assert.rejects(
    downloadUpdate({ url: a, sha256: sha(body), destDir: tmp(), get: fakeGet({ [a]: { status: 302, headers: { location: 'http://evil.com/a.dmg' } } }) }),
    e => e.code === 'BAD_URL'
  )
  const b = 'https://cdn.example.com/b.dmg'
  const r = await downloadUpdate({
    url: a, sha256: sha(body), destDir: tmp(),
    get: fakeGet({ [a]: { status: 302, headers: { location: b } }, [b]: { body } })
  })
  assert.equal(path.basename(r.file), 'a.dmg') // 文件名取最初请求的 URL
})

test('HTTP 非 200 与大小不符', async () => {
  const url = 'https://dl.example.com/a.dmg'
  const body = Buffer.from('abc')
  await assert.rejects(downloadUpdate({ url, sha256: sha(body), destDir: tmp(), get: fakeGet({ [url]: { status: 404 } }) }), e => e.code === 'HTTP_ERROR')
  const dir = tmp()
  await assert.rejects(downloadUpdate({ url, sha256: sha(body), destDir: dir, expectedSize: 99, get: fakeGet({ [url]: { body } }) }), e => e.code === 'SIZE_MISMATCH')
  assert.deepEqual(fs.readdirSync(dir), [])
})

test('真实本机 http 服务：allowLoopbackHttp 下载并校验', async () => {
  const body = crypto.randomBytes(200000)
  const srv = http.createServer((req, res) => { res.setHeader('content-length', body.length); res.end(body) })
  await new Promise(r => srv.listen(0, '127.0.0.1', r))
  const url = `http://127.0.0.1:${srv.address().port}/DongAI-0.2.0.dmg`
  try {
    const dir = tmp()
    const r = await downloadUpdate({ url, sha256: sha(body), destDir: dir, allowLoopbackHttp: true, expectedSize: body.length })
    assert.equal(r.size, body.length)
    await assert.rejects(downloadUpdate({ url, sha256: sha(Buffer.from('no')), destDir: dir, allowLoopbackHttp: true }), e => e.code === 'SHA256_MISMATCH')
  } finally {
    srv.close()
  }
})

test('版本一致性检查：VERSION 与 package.json 不一致时失败', () => {
  const d = tmp()
  fs.writeFileSync(path.join(d, 'VERSION'), '1.2.3\n')
  fs.writeFileSync(path.join(d, 'package.json'), JSON.stringify({ version: '1.2.3' }))
  assert.equal(checkVersions(path.join(d, 'VERSION'), path.join(d, 'package.json')).ok, true)
  fs.writeFileSync(path.join(d, 'package.json'), JSON.stringify({ version: '1.2.4' }))
  assert.equal(checkVersions(path.join(d, 'VERSION'), path.join(d, 'package.json')).ok, false)
  fs.writeFileSync(path.join(d, 'VERSION'), 'abc\n')
  assert.equal(checkVersions(path.join(d, 'VERSION'), path.join(d, 'package.json')).ok, false)
})
