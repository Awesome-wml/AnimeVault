// 版本更新：api/update.js 错误识别、components/update/update.js 纯函数、utils/updateGate.js 缓存与订阅
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { isUpdateRequired, isUpdateUrl, requiredInfoFromError, createUpdateApi, UPDATE_REQUIRED } from '../../src/api/update.js'
import { LICENSE_ERROR_MESSAGES } from '../../src/api/license.js'
import {
  hasUpdate, isUpdateRequiredStatus, updateBannerModel, requiredScreenModel, readDismissed, writeDismissed,
  DISMISS_KEY, formatSize, formatPublishedAt, startUpdate
} from '../../src/components/update/update.js'
import { createUpdateGate, UPDATE_STATUS_TTL_MS } from '../../src/utils/updateGate.js'

const httpError = (status, data) => ({ response: { status, data } })
const LATEST = { version: '0.3.0', notes: '修复若干问题', url: 'https://dl.example.com/a.dmg', sha256: 'a'.repeat(64), size: 5 * 1024 * 1024, published_at: '2026-11-01T08:00:00Z' }
const avail = { current_version: '0.1.0', update_available: true, latest: LATEST, force: false, update_required: false }

test('错误识别：403/426 UPDATE_REQUIRED；其它 403 不算', () => {
  assert.equal(isUpdateRequired(httpError(403, { code: UPDATE_REQUIRED })), true)
  assert.equal(isUpdateRequired(httpError(426, { code: UPDATE_REQUIRED, min_supported: '0.2.0' })), true)
  assert.equal(isUpdateRequired(httpError(403, { code: 'LICENSE_REQUIRED' })), false)
  assert.equal(isUpdateRequired(httpError(500, { code: UPDATE_REQUIRED })), false)
  assert.equal(isUpdateRequired(null), false)
  assert.equal(isUpdateRequired({ message: 'Network Error' }), false)
  assert.deepEqual(requiredInfoFromError(httpError(426, { code: UPDATE_REQUIRED, min_supported: '0.2.0', message: '请升级' })),
    { min_supported: '0.2.0', message: '请升级' })
  assert.deepEqual(requiredInfoFromError(httpError(403, { code: UPDATE_REQUIRED })), { min_supported: null, message: '' })
})

test('更新接口地址识别与 API 路径；激活页对 UPDATE_REQUIRED 有中文提示', () => {
  assert.equal(isUpdateUrl('/api/update/status'), true)
  assert.equal(isUpdateUrl('/api/update'), true)
  assert.equal(isUpdateUrl('/api/updates'), false)
  assert.equal(isUpdateUrl('/api/projects'), false)
  const calls = []
  const svc = { get: u => calls.push(['get', u]), post: u => calls.push(['post', u]) }
  const api = createUpdateApi(svc)
  api.status(); api.check()
  assert.deepEqual(calls, [['get', '/api/update/status'], ['post', '/api/update/check']])
  assert.match(LICENSE_ERROR_MESSAGES.UPDATE_REQUIRED, /升级/)
})

test('提示条：有新版本才显示；强制升级时让位给全屏页；稍后只忽略该版本', () => {
  assert.equal(hasUpdate(avail), true)
  assert.equal(hasUpdate({ update_available: false, latest: null }), false)
  assert.equal(hasUpdate(null), false)
  const m = updateBannerModel(avail)
  assert.equal(m.version, '0.3.0')
  assert.match(m.text, /0\.3\.0/)
  assert.match(m.text, /0\.1\.0/)
  assert.equal(m.hasNotes, true)
  assert.equal(updateBannerModel({ ...avail, latest: { ...LATEST, notes: '  ' } }).hasNotes, false)
  assert.equal(updateBannerModel(avail, '0.3.0'), null)                          // 稍后
  assert.equal(updateBannerModel({ ...avail, latest: { ...LATEST, version: '0.4.0' } }, '0.3.0').version, '0.4.0')  // 新版本再提示
  assert.equal(updateBannerModel({ ...avail, update_required: true }), null)     // 强制升级由全屏页接管
  assert.equal(updateBannerModel(null), null)
  assert.equal(updateBannerModel({ update_available: true, latest: null }), null)
})

test('强制升级页模型：当前版本、最低版本、更新说明、下载按钮', () => {
  assert.equal(requiredScreenModel(avail), null)
  const r = requiredScreenModel({ ...avail, update_required: true, min_supported: '0.2.0', required_message: '版本过低' })
  assert.deepEqual(r, { currentVersion: '0.1.0', minVersion: '0.2.0', latestVersion: '0.3.0', notes: '修复若干问题', message: '版本过低', canDownload: true })
  // 426 发生、更新检查还没结果：没有 latest，也要能展示页面（不可下载）
  const bare = requiredScreenModel({ current_version: '0.1.0', update_required: true, min_supported: '0.2.0', latest: null })
  assert.equal(bare.canDownload, false)
  assert.equal(bare.latestVersion, '')
  assert.equal(bare.minVersion, '0.2.0')
  assert.match(bare.message, /升级/)
  assert.equal(isUpdateRequiredStatus({ update_required: true }), true)
  assert.equal(isUpdateRequiredStatus({}), false)
})

test('稍后记忆：读写 storage，storage 不可用时静默', () => {
  const mem = new Map()
  const storage = { getItem: k => mem.get(k) ?? null, setItem: (k, v) => mem.set(k, v) }
  assert.equal(readDismissed(storage), '')
  writeDismissed(storage, '0.3.0')
  assert.equal(mem.get(DISMISS_KEY), '0.3.0')
  assert.equal(readDismissed(storage), '0.3.0')
  const broken = { getItem() { throw new Error('denied') }, setItem() { throw new Error('denied') } }
  assert.equal(readDismissed(broken), '')
  assert.doesNotThrow(() => writeDismissed(broken, '0.3.0'))
  assert.equal(readDismissed(null), '')
})

test('展示函数', () => {
  assert.equal(formatSize(5 * 1024 * 1024), '5.0 MB')
  assert.equal(formatSize(2048), '2 KB')
  assert.equal(formatSize(0), '')
  assert.equal(formatSize(null), '')
  assert.match(formatPublishedAt('2026-11-01T08:00:00Z'), /^2026-1[01]-\d{2}$/)
  assert.equal(formatPublishedAt('nope'), '')
  assert.equal(formatPublishedAt(''), '')
})

test('去更新：桌面外壳走应用内下载；失败给中文原因；浏览器只开 https 地址', async () => {
  const ok = await startUpdate(LATEST, { desktop: { downloadUpdate: async () => ({ ok: true, file: '/x.dmg' }) } })
  assert.equal(ok.ok, true); assert.equal(ok.mode, 'desktop')
  const bad = await startUpdate(LATEST, { desktop: { downloadUpdate: async () => ({ ok: false, code: 'SHA256_MISMATCH', message: 'x' }) } })
  assert.equal(bad.ok, false); assert.match(bad.message, /校验失败/)
  const boom = await startUpdate(LATEST, { desktop: { downloadUpdate: async () => { throw new Error('ipc') } } })
  assert.equal(boom.ok, false)
  const opened = []
  const web = await startUpdate(LATEST, { open: u => opened.push(u) })
  assert.equal(web.ok, true); assert.deepEqual(opened, [LATEST.url]); assert.equal(web.mode, 'browser')
  const evil = await startUpdate({ url: 'javascript:alert(1)' }, { open: u => opened.push(u) })
  assert.equal(evil.ok, false); assert.equal(opened.length, 1)
  const http = await startUpdate({ url: 'http://dl.example.com/a' }, { open: u => opened.push(u) })
  assert.equal(http.ok, false); assert.equal(opened.length, 1)
  assert.equal((await startUpdate(null, {})).ok, false)
})

test('updateGate：TTL、并发合并、失败不缓存、订阅、markRequired 立即生效', async () => {
  let n = 0
  let t = 0
  let fail = false
  const gate = createUpdateGate({ fetchStatus: async () => { n++; if (fail) throw new Error('down'); return { ...avail, n } }, now: () => t })
  const seen = []
  const unsub = gate.subscribe(s => seen.push(s.n))
  const [a, b] = await Promise.all([gate.check(), gate.check()])
  assert.equal(a.n, 1); assert.equal(b.n, 1); assert.equal(n, 1)
  t += UPDATE_STATUS_TTL_MS - 1
  await gate.check(); assert.equal(n, 1)
  t += 2
  await gate.check(); assert.equal(n, 2)
  fail = true
  assert.equal(await gate.check({ force: true }), null)       // 失败：静默返回 null
  assert.equal(gate.peek().n, 2)                              // 旧缓存保留
  fail = false
  unsub()
  await gate.check({ force: true })
  assert.deepEqual(seen, [1, 2])                              // 取消订阅后不再通知

  const events = []
  gate.subscribe(s => events.push(s.update_required === true))
  const p = gate.markRequired({ min_supported: '0.2.0', message: '请升级' })
  assert.equal(gate.peek().update_required, true)              // 同步生效，不等网络
  assert.equal(gate.peek().min_supported, '0.2.0')
  assert.equal(gate.peek().current_version, '0.1.0')           // 保留已有信息
  await p
  assert.equal(events[0], true)
  const g2 = createUpdateGate({ fetchStatus: async () => { throw new Error('down') } })
  await g2.markRequired({})                                    // 状态接口也连不上时，仍然处于需要升级
  assert.equal(g2.peek().update_required, true)
})
