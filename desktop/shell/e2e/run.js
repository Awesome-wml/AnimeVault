'use strict'
// 真实跑通脚本（Playwright _electron）。用法：
//   node e2e/run.js [dev|packaged] [场景名...]    默认 dev，全部场景
// dev      ：用 node_modules 里的 Electron 直接跑 src/（需要 DONGAI_BACKEND_CMD，缺省用 ~/.local/dongai-venv 的 python）
// packaged ：跑 out/mac-arm64/DongAI.app（先 `npm run pack`）
// 所有场景都用隔离的 userData（DONGAI_SHELL_USER_DATA），不碰真实的 ~/Library/Application Support/DongAI。
const { _electron: electron } = require('playwright-core')
const { execFileSync, spawn } = require('child_process')
const fs = require('fs')
const os = require('os')
const path = require('path')

const MODE = process.argv[2] === 'packaged' ? 'packaged' : 'dev'
const ONLY = process.argv.slice(3)
const SHELL_DIR = path.resolve(__dirname, '..')
const REPO = path.resolve(SHELL_DIR, '..', '..')
const SHOTS = path.join(SHELL_DIR, 'screenshots')
const HOME = os.homedir()
const MONGOD = process.env.DONGAI_MONGOD_BIN || path.join(HOME, '.local/dongai-spike/bin-arm64/mongodb-macos-aarch64-7.0.48/bin/mongod')
const PY = path.join(HOME, '.local/dongai-venv/bin/python')
const EXE = MODE === 'packaged'
  ? path.join(SHELL_DIR, 'out/mac-arm64/DongAI.app/Contents/MacOS/DongAI')
  : path.join(SHELL_DIR, 'node_modules/electron/dist/Electron.app/Contents/MacOS/Electron')

const results = []
const sleep = ms => new Promise(r => setTimeout(r, ms))
const alive = pid => { try { process.kill(pid, 0); return true } catch (e) { return e.code === 'EPERM' } }
const readPid = f => { try { return parseInt(fs.readFileSync(f, 'utf8').trim(), 10) || 0 } catch (_) { return 0 } }

function newUserData() { return fs.mkdtempSync(path.join(os.tmpdir(), 'dongai-e2e-')) }

function baseEnv(userData, extra = {}) {
  const env = { ...process.env, DONGAI_SHELL_USER_DATA: userData, DONGAI_SHELL_ALLOW_DEBUG: '1', DONGAI_MONGOD_BIN: MONGOD,
    NO_PROXY: '127.0.0.1,localhost', no_proxy: '127.0.0.1,localhost', DONGAI_SHELL_E2E: '1' }
  delete env.ELECTRON_RUN_AS_NODE
  delete env.MONGODB_URL
  if (MODE === 'dev') {
    env.DONGAI_BACKEND_CMD = `${PY} desktop_entry.py`
    env.DONGAI_BACKEND_CWD = path.join(REPO, 'backend')
  }
  return Object.assign(env, extra)
}

async function launch(userData, extraEnv) {
  const args = MODE === 'dev' ? [SHELL_DIR] : []
  return electron.launch({ executablePath: EXE, args, env: baseEnv(userData, extraEnv), timeout: 60000 })
}

/** 等到加载出后端同源页面（http://127.0.0.1） */
async function waitApp(app, timeout = 90000) {
  const page = await app.firstWindow()
  await page.waitForURL(/^http:\/\/127\.0\.0\.1:\d+\//, { timeout })
  return page
}

function tree(rootPid) {
  const out = execFileSync('ps', ['-A', '-o', 'pid=,ppid=,rss=,comm='], { encoding: 'utf8' })
  const rows = out.split('\n').map(l => l.trim().match(/^(\d+)\s+(\d+)\s+(\d+)\s+(.*)$/)).filter(Boolean)
    .map(m => ({ pid: +m[1], ppid: +m[2], rss: +m[3], comm: m[4] }))
  const res = []
  const walk = p => { for (const r of rows.filter(x => x.ppid === p)) { res.push(r); walk(r.pid) } }
  const self = rows.find(r => r.pid === rootPid)
  if (self) res.push(self)
  walk(rootPid)
  return res
}

async function scenario(name, fn) {
  if (ONLY.length && !ONLY.includes(name)) return
  const t0 = Date.now()
  try {
    const info = await fn()
    results.push({ name, ok: true, ms: Date.now() - t0, info })
    console.log(`PASS ${name} (${Date.now() - t0}ms)`, info || '')
  } catch (e) {
    results.push({ name, ok: false, ms: Date.now() - t0, error: e.message })
    console.log(`FAIL ${name}: ${e.stack || e.message}`)
  }
}

function assert(c, m) { if (!c) throw new Error('断言失败: ' + m) }

async function main() {
  fs.mkdirSync(SHOTS, { recursive: true })
  const cold = {}

  // ① ② ③ ④ + 度量：窗口、激活页、令牌、外部链接
  await scenario('main-flow', async () => {
    const ud = newUserData()
    const t0 = Date.now()
    const app = await launch(ud)
    const info = {}
    try {
      const page = await app.firstWindow()
      await page.waitForLoadState('domcontentloaded')
      try { await page.screenshot({ path: path.join(SHOTS, '01-splash.png') }) } catch (_) { /* 启动太快就没有 */ }
      info.title = await page.title()
      assert(info.title === 'DongAI', `窗口标题=${info.title}`)
      assert((await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].getTitle())) === 'DongAI', '原生窗口标题')
      await page.waitForURL(/^http:\/\/127\.0\.0\.1:\d+\//, { timeout: 90000 })
      // 激活页：路由 /activate，能看到机器码
      await page.waitForFunction(() => /本机机器码[\s\S]*[A-Z0-9]{5}\s+[A-Z0-9]{5}\s+[A-Z0-9]{5}/.test(document.body.innerText) && location.hash.includes('activate'), null, { timeout: 60000 })
      info.coldStartToActivateMs = Date.now() - t0
      info.hash = await page.evaluate(() => location.hash)
      info.machineCodeVisible = true
      await page.waitForTimeout(800)
      await page.screenshot({ path: path.join(SHOTS, '02-activate.png') })
      // 令牌与 /api
      const r = await page.evaluate(async () => {
        const t = window.dongaiDesktop && window.dongaiDesktop.localToken
        const tokenOk = typeof t === 'string' && t.length >= 20
        const withHeader = await fetch('/api/license/status', { headers: { 'X-DongAI-Local-Token': t } })
        const noHeader = await fetch('/api/license/status')
        const pageAssets = await fetch('/')
        return { tokenOk, platform: window.dongaiDesktop.platform, version: window.dongaiDesktop.version,
          withHeader: withHeader.status, noHeader: noHeader.status, root: pageAssets.status,
          isolated: typeof require === 'undefined' && typeof process === 'undefined' }
      })
      assert(r.tokenOk, '令牌存在')
      assert(r.withHeader === 200 && r.noHeader === 401 && r.root === 200, `状态码 ${JSON.stringify(r)}`)
      assert(r.isolated, '页面不应有 require/process')
      info.api = { withHeader: r.withHeader, noHeader: r.noHeader, platform: r.platform, version: r.version }
      // 页面自己的 axios 请求（激活页的状态接口）也要成功：看控制台没有 401
      // 外部链接
      await app.evaluate(({ shell }) => { globalThis.__opened = []; shell.openExternal = u => { globalThis.__opened.push(u); return Promise.resolve() } })
      const before = app.windows().length
      await page.evaluate(() => { window.open('https://example.com/a', '_blank') })
      await page.evaluate(() => {
        const a = document.createElement('a'); a.href = 'https://example.org/b'; a.target = '_blank'; a.id = '__lnk'; a.textContent = 'x'
        document.body.appendChild(a); a.click()
      })
      const curUrl = page.url()
      await page.evaluate(() => { location.href = 'https://example.net/c' }).catch(() => {})
      await sleep(800)
      info.openedExternally = await app.evaluate(() => globalThis.__opened)
      assert(app.windows().length === before, '不应出现新窗口')
      assert(page.url() === curUrl || page.url().startsWith('http://127.0.0.1'), `页面被导航走了: ${page.url()}`)
      assert(info.openedExternally.includes('https://example.com/a') && info.openedExternally.includes('https://example.org/b') && info.openedExternally.includes('https://example.net/c'), '外部链接应交给系统浏览器 ' + JSON.stringify(info.openedExternally))
      // javascript:/file: 不外开
      const n = info.openedExternally.length
      await page.evaluate(() => { window.open('file:///etc/passwd'); window.open('javascript:alert(1)') })
      await sleep(300)
      assert((await app.evaluate(() => globalThis.__opened)).length === n, 'file:/javascript: 不应外开')
      // CSP 响应头
      const resp = await page.reload()
      const csp = resp.headers()['content-security-policy'] || ''
      info.csp = csp
      assert(csp.includes("default-src 'self'") && csp.includes("object-src 'none'"), 'CSP 响应头')
      await page.waitForFunction(() => window.dongaiDesktop && location.hash.includes('activate'), null, { timeout: 30000 })
      const errs = await page.evaluate(() => document.body.innerText.includes('本机机器码'))
      assert(errs, 'CSP 下页面仍正常渲染')
      // 权限请求被拒
      info.permission = await page.evaluate(async () => {
        try { return (await Notification.requestPermission()) } catch (e) { return 'err' }
      })
      // 度量：空闲内存
      await sleep(15000)
      const pid = app.process().pid
      const procs = tree(pid)
      info.rssMB = Math.round(procs.reduce((a, p) => a + p.rss, 0) / 1024)
      info.procs = procs.map(p => `${path.basename(p.comm)}:${Math.round(p.rss / 1024)}MB`).join(' ')
      cold.userData = ud
      // ⑤ 单实例锁
      const second = spawn(EXE, MODE === 'dev' ? [SHELL_DIR] : [], { env: baseEnv(ud), stdio: 'ignore' })
      const code = await new Promise(res => { const t = setTimeout(() => { second.kill('SIGKILL'); res('timeout') }, 20000); second.on('exit', c => { clearTimeout(t); res(c) }) })
      info.secondInstanceExit = code
      assert(code === 0, `第二个实例应立即退出，实际 ${code}`)
      assert(app.windows().length === 1, '仍只有一个窗口')
      // ⑥ 正常退出，进程不残留
      const backendPid = readPid(path.join(ud, 'sidecar.pid'))
      const mongodPid = readPid(path.join(ud, 'mongod.pid'))
      info.pids = { backendPid, mongodPid }
      assert(backendPid && mongodPid && alive(backendPid) && alive(mongodPid), '退出前后端和 mongod 在运行')
      await app.close()
      await sleep(1500)
      assert(!alive(backendPid), '后端应已退出')
      assert(!alive(mongodPid), 'mongod 应已退出')
      info.cleanExit = true
    } finally { try { await app.close() } catch (_) { /* 已关 */ } }
    return info
  })

  // ⑦ 强杀 Electron 主进程后，下次启动清理遗留并正常启动
  await scenario('kill9-recovery', async () => {
    const ud = newUserData()
    const app = await launch(ud)
    const info = {}
    const mainPid = app.process().pid
    await waitApp(app)
    const backendPid = readPid(path.join(ud, 'sidecar.pid'))
    const mongodPid = readPid(path.join(ud, 'mongod.pid'))
    process.kill(mainPid, 'SIGKILL')
    await sleep(1500)
    info.orphansAfterKill9 = { backend: alive(backendPid), mongod: alive(mongodPid) }
    assert(alive(backendPid) && alive(mongodPid), '（前置）强杀后应留下遗留进程，否则测试没意义')
    const app2 = await launch(ud)
    try {
      const page = await waitApp(app2)
      await page.waitForFunction(() => location.hash.includes('activate'), null, { timeout: 60000 })
      info.oldBackendAlive = alive(backendPid)
      info.oldMongodAlive = alive(mongodPid)
      assert(!info.oldBackendAlive && !info.oldMongodAlive, '旧的后端/mongod 应已被清理')
      const newBackend = readPid(path.join(ud, 'sidecar.pid'))
      assert(newBackend && newBackend !== backendPid && alive(newBackend), '新后端在运行')
      const st = await page.evaluate(async () => (await fetch('/api/license/status', { headers: { 'X-DongAI-Local-Token': window.dongaiDesktop.localToken } })).status)
      assert(st === 200, '新后端 API 可用')
      const nm = readPid(path.join(ud, 'mongod.pid'))
      await app2.close()
      await sleep(1500)
      assert(!alive(newBackend) && !alive(nm), '第二次正常退出无残留')
    } finally { try { await app2.close() } catch (_) { /* */ } }
    return info
  })

  // ⑧ 启动失败页：坏命令 / 后端秒退 / Mongo 失败 / 超时
  const failCase = (name, extra, expectTitle, shot) => scenario(name, async () => {
    const ud = newUserData()
    const app = await launch(ud, extra)
    try {
      const page = await app.firstWindow()
      await page.waitForFunction(() => document.getElementById('title') && document.getElementById('title').textContent.length > 0, null, { timeout: 60000 })
      const title = await page.textContent('#title')
      assert(title === expectTitle, `错误页标题 ${title} != ${expectTitle}`)
      const btns = await page.evaluate(() => [...document.querySelectorAll('button')].map(b => b.textContent))
      assert(btns.includes('打开日志文件夹') && btns.includes('重试'), '按钮 ' + btns)
      if (shot) await page.screenshot({ path: path.join(SHOTS, shot) })
      await app.evaluate(({ shell }) => { globalThis.__paths = []; shell.openPath = p => { globalThis.__paths.push(p); return Promise.resolve('') } })
      await page.click('#logs')
      await sleep(300)
      const paths = await app.evaluate(() => globalThis.__paths)
      assert(paths.length === 1 && paths[0] === path.join(ud, 'logs'), '打开日志目录 ' + JSON.stringify(paths))
      assert(fs.existsSync(path.join(ud, 'logs', 'shell-backend.log')), '日志文件存在')
      return { title, btns, openedLogs: paths[0] }
    } finally { await app.close() }
  })
  await failCase('fail-bad-command', { DONGAI_BACKEND_CMD: '/nonexistent/backend-binary' }, '后端未能启动', '03-error-spawn.png')
  await failCase('fail-mongo', { DONGAI_MONGOD_BIN: '/nonexistent/mongod' }, 'Mongo 启动失败', '04-error-mongo.png')
  await failCase('fail-timeout', { DONGAI_BACKEND_CMD: '/bin/sleep 120', DONGAI_SHELL_READY_TIMEOUT_MS: '4000' }, '启动超时', null)

  // 崩溃：自动重试 2 次，之后显示「重启服务」
  await scenario('crash-autoretry', async () => {
    const ud = newUserData()
    const app = await launch(ud)
    const info = {}
    try {
      const page = await waitApp(app)
      const pidFile = path.join(ud, 'sidecar.pid')
      let prev = readPid(pidFile)
      for (let i = 1; i <= 2; i++) {
        process.kill(prev, 'SIGKILL')
        const t0 = Date.now()
        let cur = prev
        while (Date.now() - t0 < 90000 && (cur === prev || !alive(cur))) { await sleep(500); cur = readPid(pidFile) || prev }
        assert(cur !== prev, `第 ${i} 次自动重启`)
        await page.waitForURL(/^http:\/\/127\.0\.0\.1:\d+\//, { timeout: 90000 })
        await page.waitForFunction(() => window.dongaiDesktop && location.hash.includes('activate'), null, { timeout: 60000 })
        prev = cur
      }
      info.autoRestarts = 2
      process.kill(prev, 'SIGKILL')
      await page.waitForFunction(() => document.getElementById('title') && document.getElementById('title').textContent === '后端服务已停止', null, { timeout: 30000 })
      const btn = await page.textContent('#retry')
      assert(btn === '重启服务', '按钮文案 ' + btn)
      await page.screenshot({ path: path.join(SHOTS, '05-error-crash.png') })
      await sleep(2000)
      const mp = readPid(path.join(ud, 'mongod.pid'))
      info.mongodLeftAfterCrash = mp ? alive(mp) : false
      assert(!info.mongodLeftAfterCrash, '崩溃后不应留下 mongod')
      // 点「重启服务」恢复
      await page.click('#retry')
      await page.waitForURL(/^http:\/\/127\.0\.0\.1:\d+\//, { timeout: 90000 })
      info.recovered = true
    } finally { await app.close() }
    return info
  })

  // 窗口状态记忆
  await scenario('window-state', async () => {
    const ud = newUserData()
    let app = await launch(ud)
    const info = {}
    try {
      await waitApp(app)
      info.defaultSize = await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].getSize())
      assert(info.defaultSize[0] === 1440 && info.defaultSize[1] === 900, `默认尺寸 ${info.defaultSize}`)
      await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].setBounds({ x: 60, y: 60, width: 1200, height: 760 }))
      await sleep(1000)
      await app.close()
      app = await launch(ud)
      await waitApp(app)
      info.restored = await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].getBounds())
      assert(info.restored.width === 1200 && info.restored.height === 760, `恢复尺寸 ${JSON.stringify(info.restored)}`)
      const min = await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].getMinimumSize())
      assert(min[0] === 1100 && min[1] === 700, '最小尺寸')
    } finally { await app.close() }
    return info
  })

  console.log('\n==== 汇总 ====')
  for (const r of results) console.log(`${r.ok ? 'PASS' : 'FAIL'}  ${r.name}  ${r.ms}ms${r.ok ? '' : '  ' + r.error}`)
  process.exit(results.every(r => r.ok) ? 0 : 1)
}

main().catch(e => { console.error(e); process.exit(2) })
