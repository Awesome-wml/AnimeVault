'use strict'
const { app, BrowserWindow, ipcMain, screen, session, shell } = require('electron')
const path = require('path')
const { pathToFileURL } = require('url')

// 必须在 ready 之前：应用名固定为 DongAI，userData 与后端默认数据目录一致
app.setName('DongAI')
if (process.env.DONGAI_SHELL_USER_DATA) {
  // 自动化测试用：隔离数据目录，不碰真实的 ~/Library/Application Support/DongAI
  app.setPath('userData', process.env.DONGAI_SHELL_USER_DATA)
}

const { buildSidecarEnv, resolveBackend, resolveFrontendDir } = require('./backend-path')
const { checkChrome } = require('./chrome-check')
const { RotatingLog } = require('./log-rotate')
const { buildMenu } = require('./menu')
const { guardWebContents, installSessionSecurity } = require('./security')
const { Sidecar, cleanupStale, killStaleMongod } = require('./sidecar')
const { initUpdater } = require('./updater')
const { fitToDisplays, loadWindowState, saveWindowState, MIN } = require('./window-state')

const ALLOW_DEBUG = process.env.DONGAI_SHELL_ALLOW_DEBUG === '1'
const REPO_ROOT = path.resolve(__dirname, '..', '..', '..')
const PAGES_DIR = path.join(__dirname, 'pages')
const MAX_AUTO_RETRIES = 2

// 禁用远程调试端口：打包后拒绝带 --remote-debugging-* / --inspect* 启动（自动化测试用 DONGAI_SHELL_ALLOW_DEBUG=1 放行）
if (app.isPackaged && !ALLOW_DEBUG &&
    process.argv.some(a => /^--(remote-debugging|inspect)/.test(a))) {
  console.error('DongAI: 不允许开启调试端口')
  app.exit(2)
}

let win = null
let sidecar = null
let ctx = null // { origin, token }
let chrome = { installed: true, path: null }
let quitting = false
let autoRetries = 0
let startedAt = 0
let booting = false
let log = null
let updater = null

const dataDir = () => app.getPath('userData')
const logsDir = () => path.join(dataDir(), 'logs')
const stateFile = () => path.join(dataDir(), 'window-state.json')

function pageUrl(name, params = {}) {
  const u = pathToFileURL(path.join(PAGES_DIR, name))
  for (const [k, v] of Object.entries(params)) u.searchParams.set(k, String(v))
  return u.toString()
}

function isOwnPageUrl(u) {
  return u.startsWith(pathToFileURL(PAGES_DIR).toString())
}

function isAllowedUrl(u) {
  if (isOwnPageUrl(u)) return true
  return !!ctx && (u === ctx.origin || u.startsWith(ctx.origin + '/'))
}

// ---------------------------------------------------------------- 窗口
function createWindow() {
  const saved = fitToDisplays(loadWindowState(stateFile()), screen.getAllDisplays().map(d => d.workArea))
  win = new BrowserWindow({
    width: saved.width,
    height: saved.height,
    x: saved.x,
    y: saved.y,
    minWidth: MIN.width,
    minHeight: MIN.height,
    title: 'DongAI',
    backgroundColor: '#0f1115',
    show: false,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      devTools: !app.isPackaged || ALLOW_DEBUG
    }
  })
  if (saved.maximized) win.maximize()
  win.once('ready-to-show', () => win && win.show())
  win.on('page-title-updated', e => e.preventDefault())

  let timer = null
  const persist = () => {
    clearTimeout(timer)
    timer = setTimeout(() => {
      if (!win || win.isDestroyed() || win.isMinimized() || win.isFullScreen()) return
      const maximized = win.isMaximized()
      const b = win.getNormalBounds()
      saveWindowState(stateFile(), { ...b, maximized })
    }, 400)
  }
  win.on('resize', persist)
  win.on('move', persist)
  win.on('close', () => {
    if (!win.isMinimized() && !win.isFullScreen()) {
      saveWindowState(stateFile(), { ...win.getNormalBounds(), maximized: win.isMaximized() })
    }
  })
  win.on('closed', () => { win = null })

  win.webContents.on('did-finish-load', () => {
    if (!chrome.installed && ctx && win.webContents.getURL().startsWith(ctx.origin)) {
      win.webContents.send('dongai:chrome-missing')
    }
  })
  win.webContents.on('render-process-gone', (_e, d) => log && log.write(`[shell] 渲染进程退出: ${d.reason}`))
  return win
}

function ensureWindow() {
  if (!win) createWindow()
  return win
}

function showSplash(msg, hint) {
  const params = {}
  if (msg) params.msg = msg
  if (hint) params.hint = hint
  ensureWindow().loadURL(pageUrl('splash.html', params))
}

function showError(kind, detail) {
  ensureWindow().loadURL(pageUrl('error.html', { kind, detail: detail || '' }))
}

// ---------------------------------------------------------------- sidecar
async function bootBackend({ auto = false } = {}) {
  if (booting || quitting) return
  booting = true
  try {
    ctx = null
    if (!auto) autoRetries = 0
    showSplash(auto ? `服务异常，正在重启（${autoRetries}/${MAX_AUTO_RETRIES}）…` : '正在启动…')
    const pidFile = path.join(dataDir(), 'sidecar.pid')
    await cleanupStale(pidFile, m => log.write(`[shell] ${m}`))

    const repoRoot = REPO_ROOT
    let command
    try {
      command = resolveBackend({
        env: process.env, isPackaged: app.isPackaged, resourcesPath: process.resourcesPath,
        platform: process.platform, repoRoot, home: require('os').homedir()
      })
    } catch (e) {
      log.write(`[shell] ${e.message}`)
      return showError('spawn', e.message)
    }
    const env = buildSidecarEnv({
      base: process.env, dataDir: dataDir(), isPackaged: app.isPackaged,
      frontendDir: resolveFrontendDir({ env: process.env, isPackaged: app.isPackaged, resourcesPath: process.resourcesPath, repoRoot })
    })
    sidecar = new Sidecar({ command, env, log, pidFile, readyTimeoutMs: Number(process.env.DONGAI_SHELL_READY_TIMEOUT_MS) || 90000 })
    let info
    try {
      info = await sidecar.start()
    } catch (e) {
      log.write(`[shell] 启动失败 kind=${e.kind || 'spawn'}: ${e.message}`)
      await sidecar.stop(5000).catch(() => {})
      const tail = (e.tail || []).slice(-6).join('\n')
      return showError(e.kind || 'spawn', `${e.message}\n${tail}`)
    }
    if (quitting) return
    ctx = { origin: `http://127.0.0.1:${info.port}`, token: info.token }
    startedAt = Date.now()
    sidecar.on('crash', onCrash)
    chrome = checkChrome()
    await ensureWindow().loadURL(ctx.origin + '/')
  } finally {
    booting = false
  }
}

async function onCrash({ code, signal, tail }) {
  if (quitting) return
  log.write(`[shell] 后端意外退出 code=${code} signal=${signal}`)
  ctx = null
  await killStaleMongod(dataDir(), m => log.write(`[shell] ${m}`)).catch(() => {}) // 后端没来得及停 mongod
  if (Date.now() - startedAt > 5 * 60 * 1000) autoRetries = 0 // 稳定运行过就重新计数
  if (autoRetries < MAX_AUTO_RETRIES) {
    autoRetries += 1
    bootBackend({ auto: true }).catch(e => log.write(`[shell] 自动重启失败: ${e.message}`))
  } else {
    showError('crash', `退出码 ${code}${signal ? ' / ' + signal : ''}\n${(tail || []).slice(-6).join('\n')}`)
  }
}

async function shutdown() {
  if (sidecar) await sidecar.stop(20000).catch(() => {})
  if (log) log.close()
}

// ---------------------------------------------------------------- IPC
function fromOrigin(event) {
  const url = (event.senderFrame && event.senderFrame.url) || ''
  return !!ctx && url.startsWith(ctx.origin + '/')
}
function fromOwnPage(event) {
  const url = (event.senderFrame && event.senderFrame.url) || ''
  return isOwnPageUrl(url)
}

ipcMain.on('dongai:get-init', event => {
  event.returnValue = fromOrigin(event)
    ? { localToken: ctx.token, platform: process.platform, version: app.getVersion() }
    : {}
})
ipcMain.handle('dongai:chrome-status', event => (fromOrigin(event) ? chrome : null))
ipcMain.on('shell:open-logs', event => { if (fromOwnPage(event)) shell.openPath(logsDir()) })
ipcMain.on('shell:retry', event => { if (fromOwnPage(event)) bootBackend().catch(e => log.write(`[shell] 重试失败: ${e.message}`)) })

// ---------------------------------------------------------------- 生命周期
if (!app.requestSingleInstanceLock()) {
  app.exit(0)
} else {
  app.on('second-instance', () => {
    if (win) {
      if (win.isMinimized()) win.restore()
      win.show()
      win.focus()
    }
  })

  app.on('web-contents-created', (_e, contents) => guardWebContents(contents, { isAllowedUrl }))

  app.whenReady().then(async () => {
    log = new RotatingLog(logsDir())
    log.write(`[shell] DongAI ${app.getVersion()} 启动 pid=${process.pid} packaged=${app.isPackaged} userData=${dataDir()}`)
    installSessionSecurity(session.defaultSession, () => (ctx ? ctx.origin : ''))
    require('electron').Menu.setApplicationMenu(buildMenu({ logsDir: logsDir(), dataDir: dataDir() }))
    updater = initUpdater({ app, getWindow: () => win, log })
    createWindow()
    await bootBackend()
  })

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0 && !quitting) {
      createWindow()
      if (ctx) win.loadURL(ctx.origin + '/')
      else if (booting) showSplash('正在启动…')
      else bootBackend().catch(() => {})
    }
  })

  app.on('window-all-closed', () => {
    if (process.platform !== 'darwin') app.quit()
  })

  app.on('before-quit', e => {
    if (quitting) return
    quitting = true
    e.preventDefault()
    shutdown().finally(() => app.exit(0))
  })

  for (const sig of ['SIGTERM', 'SIGINT', 'SIGHUP']) process.on(sig, () => app.quit())
}
