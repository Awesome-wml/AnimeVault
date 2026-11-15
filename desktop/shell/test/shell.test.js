'use strict'
const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('fs')
const os = require('os')
const path = require('path')

const { parseReadyLine, redact, LineSplitter } = require('../src/ready-parser')
const { loadWindowState, saveWindowState, fitToDisplays, DEFAULTS } = require('../src/window-state')
const { splitCommand, resolveBackend, resolveFrontendDir, buildSidecarEnv } = require('../src/backend-path')
const { RotatingLog } = require('../src/log-rotate')
const { checkChrome } = require('../src/chrome-check')

const tmp = () => fs.mkdtempSync(path.join(os.tmpdir(), 'dongai-shell-'))

test('ready 行解析：前后杂音、非 ready JSON、非法端口', () => {
  assert.deepEqual(parseReadyLine('{"event":"ready","port":5123,"token":"abc"}'), { port: 5123, token: 'abc' })
  assert.deepEqual(parseReadyLine('  INFO: x {"event":"ready","port":1,"token":"t"} tail'), { port: 1, token: 't' })
  assert.equal(parseReadyLine('{"event":"starting"}'), null)
  assert.equal(parseReadyLine('INFO: Uvicorn running on http://127.0.0.1:5123'), null)
  assert.equal(parseReadyLine('{"event":"ready","port":0,"token":"t"}'), null)
  assert.equal(parseReadyLine('{"event":"ready","port":80}'), null)
  assert.equal(parseReadyLine('{"event":"ready","port":80,"token":'), null)
})

test('分片到达与 ready 之前的杂音', () => {
  const sp = new LineSplitter()
  let lines = []
  for (const c of ['noise 1\nnoi', 'se 2\n{"event":"rea', 'dy","port":777,"tok', 'en":"zz"}\r\nafter']) lines.push(...sp.feed(c))
  assert.deepEqual(lines, ['noise 1', 'noise 2', '{"event":"ready","port":777,"token":"zz"}'])
  assert.deepEqual(sp.flush(), ['after'])
  assert.deepEqual(parseReadyLine(lines[2]), { port: 777, token: 'zz' })
})

test('令牌脱敏：字段与已知值', () => {
  const line = '{"event":"ready","port":1,"token":"SECRET-1"}'
  const out = redact(line, 'SECRET-1')
  assert.ok(!out.includes('SECRET-1'))
  assert.match(out, /"event":"ready"/)
  assert.ok(!redact('请求头 X-Token: SECRET-1 出错', 'SECRET-1').includes('SECRET-1'))
  assert.ok(!redact('{"token": "other"}', '').includes('other'))
})

test('窗口状态：读写、缺失与损坏回退、非法数值', () => {
  const d = tmp()
  const f = path.join(d, 'sub', 'ws.json')
  assert.deepEqual(loadWindowState(f), { ...DEFAULTS, maximized: false })
  assert.ok(saveWindowState(f, { x: 10, y: 20, width: 1300, height: 800, maximized: true }))
  assert.deepEqual(loadWindowState(f), { x: 10, y: 20, width: 1300, height: 800, maximized: true })
  fs.writeFileSync(f, '{broken')
  assert.equal(loadWindowState(f).width, 1440)
  fs.writeFileSync(f, JSON.stringify({ width: 10, height: 10 }))
  assert.equal(loadWindowState(f).width, 1440) // 小于最小尺寸
  assert.equal(saveWindowState(f, { width: 'a', height: 5 }), false)
})

test('窗口位置落在显示器之外时丢弃坐标', () => {
  const displays = [{ x: 0, y: 0, width: 1920, height: 1080 }]
  assert.equal(fitToDisplays({ x: 100, y: 100, width: 1200, height: 800 }, displays).x, 100)
  const r = fitToDisplays({ x: 5000, y: 100, width: 1200, height: 800 }, displays)
  assert.equal(r.x, undefined)
  assert.equal(r.width, 1200)
})

test('命令切分：引号、转义、~', () => {
  assert.deepEqual(splitCommand('~/v/bin/python backend/desktop_entry.py', '/h'), ['/h/v/bin/python', 'backend/desktop_entry.py'])
  assert.deepEqual(splitCommand('"/a b/py" -c \'x y\' ""', '/h'), ['/a b/py', '-c', 'x y', ''])
  assert.throws(() => splitCommand('"abc'))
})

test('sidecar 路径解析：开发/打包/打包后忽略环境变量', () => {
  const base = { isPackaged: false, resourcesPath: '/R', platform: 'darwin', repoRoot: '/repo', home: '/h' }
  assert.throws(() => resolveBackend({ ...base, env: {} }), /DONGAI_BACKEND_CMD/)
  const dev = resolveBackend({ ...base, env: { DONGAI_BACKEND_CMD: '~/py desktop_entry.py' } })
  assert.deepEqual([dev.cmd, dev.args, dev.cwd], ['/h/py', ['desktop_entry.py'], '/repo/backend'])
  const pk = { ...base, isPackaged: true }
  assert.equal(resolveBackend({ ...pk, env: { DONGAI_BACKEND_CMD: 'evil' } }).cmd, '/R/backend/dongai-backend')
  assert.equal(resolveBackend({ ...pk, platform: 'win32', env: {} }).cmd, path.join('/R/backend', 'dongai-backend.exe'))
  assert.equal(resolveBackend({ ...pk, env: { DONGAI_BACKEND_CMD: 'x y', DONGAI_SHELL_ALLOW_DEBUG: '1' } }).cmd, 'x')
  assert.equal(resolveFrontendDir({ env: {}, isPackaged: true, resourcesPath: '/R', repoRoot: '/repo' }), '/R/frontend')
  assert.equal(resolveFrontendDir({ env: {}, isPackaged: false, resourcesPath: '/R', repoRoot: '/repo' }), path.join('/repo', 'frontend', 'dist'))
})

test('sidecar 环境变量', () => {
  const env = buildSidecarEnv({ base: { MONGODB_URL: 'mongodb://x', DONGAI_LOCAL_TOKEN: 'old', A: '1' }, dataDir: '/d', frontendDir: '/f', isPackaged: true })
  assert.equal(env.DONGAI_DESKTOP, '1')
  assert.equal(env.DONGAI_DATA_DIR, '/d')
  assert.equal(env.DONGAI_FRONTEND_DIR, '/f')
  assert.equal(env.MONGODB_URL, undefined)
  assert.equal(env.DONGAI_LOCAL_TOKEN, undefined)
  assert.equal(env.A, '1')
})

test('滚动日志：超限轮转并只保留 keep 个', () => {
  const d = tmp()
  const lg = new RotatingLog(d, 'x.log', { maxBytes: 100, keep: 3 })
  for (let i = 0; i < 40; i++) lg.write('line-' + String(i).padStart(2, '0') + ' ' + 'x'.repeat(20))
  lg.close()
  const files = fs.readdirSync(d).sort()
  assert.deepEqual(files, ['x.log', 'x.log.1', 'x.log.2', 'x.log.3'])
  for (const f of files) assert.ok(fs.statSync(path.join(d, f)).size <= 100)
  assert.ok(fs.readFileSync(path.join(d, 'x.log'), 'utf8').includes('line-39'))
})

test('Chrome 检测', () => {
  assert.deepEqual(checkChrome({ platform: 'darwin', home: '/h', exists: p => p === '/Applications/Google Chrome.app' }),
    { installed: true, path: '/Applications/Google Chrome.app' })
  assert.equal(checkChrome({ platform: 'darwin', home: '/h', exists: () => false }).installed, false)
  assert.equal(checkChrome({ platform: 'win32', env: { PROGRAMFILES: 'C:\\PF' }, exists: () => false, registry: () => null }).installed, false)
  assert.equal(checkChrome({ platform: 'win32', env: {}, exists: p => p === 'D:\\chrome.exe', registry: () => 'D:\\chrome.exe' }).installed, true)
})
