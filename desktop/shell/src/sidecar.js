'use strict'
const { spawn, execFileSync } = require('child_process')
const { EventEmitter } = require('events')
const fs = require('fs')
const { LineSplitter, parseReadyLine, redact } = require('./ready-parser')

const IS_WIN = process.platform === 'win32'

class SidecarError extends Error {
  /** kind: spawn（后端未能启动）| mongo（Mongo 启动失败）| timeout | exit（运行中退出） */
  constructor(kind, message, tail = []) {
    super(message)
    this.kind = kind
    this.tail = tail
  }
}

function pidAlive(pid) {
  try { process.kill(pid, 0); return true } catch (e) { return e.code === 'EPERM' }
}

/** 所有后代进程 pid（POSIX 用 ps；Windows 交给 taskkill /T，不需要列举） */
function descendants(pid) {
  if (IS_WIN) return []
  try {
    const out = execFileSync('ps', ['-A', '-o', 'pid=,ppid='], { encoding: 'utf8' })
    const kids = new Map()
    for (const line of out.split('\n')) {
      const m = line.trim().match(/^(\d+)\s+(\d+)$/)
      if (!m) continue
      const [p, pp] = [Number(m[1]), Number(m[2])]
      if (!kids.has(pp)) kids.set(pp, [])
      kids.get(pp).push(p)
    }
    const res = []
    const walk = x => { for (const k of kids.get(x) || []) { res.push(k); walk(k) } }
    walk(pid)
    return res
  } catch (_) { return [] }
}

function sendSignal(pid, sig) {
  try { process.kill(pid, sig) } catch (_) { /* 已退出 */ }
}

function processCommand(pid) {
  if (IS_WIN) return ''
  try { return execFileSync('ps', ['-p', String(pid), '-o', 'command='], { encoding: 'utf8' }).trim() } catch (_) { return '' }
}

const sleep = ms => new Promise(r => setTimeout(r, ms))

async function waitDead(pids, timeoutMs) {
  const end = Date.now() + timeoutMs
  while (Date.now() < end) {
    if (pids.every(p => !pidAlive(p))) return true
    await sleep(100)
  }
  return pids.every(p => !pidAlive(p))
}

/** 结束进程树：先礼后兵。返回是否全部退出 */
async function killTree(pid, { graceMs = 20000 } = {}) {
  if (!pid) return true
  if (IS_WIN) {
    try { execFileSync('taskkill', ['/T', '/PID', String(pid)], { stdio: 'ignore', windowsHide: true }) } catch (_) { /* ignore */ }
    if (await waitDead([pid], graceMs)) return true
    try { execFileSync('taskkill', ['/F', '/T', '/PID', String(pid)], { stdio: 'ignore', windowsHide: true }) } catch (_) { /* ignore */ }
    return waitDead([pid], 5000)
  }
  const all = [pid, ...descendants(pid)]
  sendSignal(pid, 'SIGTERM')
  if (await waitDead(all, graceMs)) return true
  for (const p of [...new Set([...all, ...descendants(pid)])].reverse()) sendSignal(p, 'SIGKILL')
  return waitDead(all, 5000)
}

/** 上次外壳被强杀留下的后端：按 pid 文件找到并结束（mongod 由后端 L-05 机制在下次启动时清理，这里连带结束整棵树） */
async function cleanupStale(pidFile, log = () => {}) {
  let pid = 0
  try { pid = parseInt(fs.readFileSync(pidFile, 'utf8').trim(), 10) } catch (_) { return false }
  let killed = false
  if (pid > 1 && pidAlive(pid)) {
    const cmd = processCommand(pid)
    if (/dongai-backend|desktop_entry/.test(cmd) || IS_WIN) {
      log(`清理上次遗留的后端进程 pid=${pid}`)
      await killTree(pid, { graceMs: 10000 })
      killed = true
    }
  }
  try { fs.unlinkSync(pidFile) } catch (_) { /* ignore */ }
  return killed
}

/** 后端被强杀/崩溃后留下的 mongod（后端把 pid 写在 <数据目录>/mongod.pid）：确认是 mongod 再结束 */
async function killStaleMongod(dataDir, log = () => {}) {
  const f = require('path').join(dataDir, 'mongod.pid')
  let pid = 0
  try { pid = parseInt(fs.readFileSync(f, 'utf8').trim(), 10) } catch (_) { return false }
  if (pid > 1 && pidAlive(pid) && (IS_WIN || /mongod/.test(processCommand(pid)))) {
    log(`结束遗留的 mongod pid=${pid}`)
    await killTree(pid, { graceMs: 10000 })
    try { fs.unlinkSync(f) } catch (_) { /* ignore */ }
    return true
  }
  return false
}

function classify(tail) {
  const text = tail.join('\n')
  return /mongod|mongodb|MongodError|Mongo /i.test(text) ? 'mongo' : 'spawn'
}

class Sidecar extends EventEmitter {
  constructor({ command, env, log, pidFile, readyTimeoutMs = 90000 }) {
    super()
    this.command = command
    this.env = env
    this.log = log // { write(text) }
    this.pidFile = pidFile
    this.readyTimeoutMs = readyTimeoutMs
    this.child = null
    this.token = ''
    this.ready = false
    this.stopping = false
    this.tail = []
  }

  _write(line) {
    const clean = redact(line, this.token)
    this.tail.push(clean)
    if (this.tail.length > 60) this.tail.shift()
    try { this.log.write(clean) } catch (_) { /* 日志失败不影响运行 */ }
  }

  start() {
    return new Promise((resolve, reject) => {
      let settled = false
      const done = (fn, v) => {
        if (settled) return
        settled = true
        clearTimeout(timer)
        fn(v)
      }
      const { cmd, args, cwd } = this.command
      this._write(`[shell] 启动后端: ${cmd} ${args.join(' ')}`)
      let child
      try {
        child = spawn(cmd, args, { cwd, env: this.env, stdio: ['ignore', 'pipe', 'pipe'], windowsHide: true })
      } catch (e) {
        return reject(new SidecarError('spawn', `无法启动后端: ${e.message}`, this.tail))
      }
      this.child = child
      if (this.pidFile && child.pid) {
        try { fs.writeFileSync(this.pidFile, String(child.pid)) } catch (_) { /* ignore */ }
      }
      const timer = setTimeout(() => {
        done(reject, new SidecarError('timeout', `后端在 ${Math.round(this.readyTimeoutMs / 1000)} 秒内没有就绪`, this.tail))
      }, this.readyTimeoutMs)

      const onData = splitter => chunk => {
        for (const line of splitter.feed(chunk)) {
          if (!this.ready) {
            const ev = parseReadyLine(line)
            if (ev) {
              this.token = ev.token
              this.ready = true
              this._write(line) // 经过脱敏
              return done(resolve, { port: ev.port, token: ev.token })
            }
          }
          this._write(line)
        }
      }
      const outSplit = new LineSplitter()
      const errSplit = new LineSplitter()
      child.stdout.on('data', onData(outSplit))
      child.stderr.on('data', onData(errSplit))
      child.on('error', e => {
        this._write(`[shell] 后端进程错误: ${e.message}`)
        done(reject, new SidecarError('spawn', `无法启动后端: ${e.message}`, this.tail))
      })
      child.on('exit', (code, signal) => {
        for (const l of [...outSplit.flush(), ...errSplit.flush()]) this._write(l)
        this._write(`[shell] 后端退出 code=${code} signal=${signal}`)
        if (this.pidFile) { try { fs.unlinkSync(this.pidFile) } catch (_) { /* ignore */ } }
        const expected = this.stopping
        if (!this.ready) {
          done(reject, new SidecarError(classify(this.tail), `后端启动过程中退出 (code=${code})`, this.tail))
        } else if (!expected) {
          this.emit('crash', { code, signal, tail: this.tail.slice() })
        }
        this.emit('exit', { code, signal, expected })
      })
    })
  }

  /** 优雅停止（SIGTERM / taskkill /T），超时强杀，连 mongod 一起 */
  async stop(graceMs = 20000) {
    this.stopping = true
    const child = this.child
    if (!child || child.exitCode !== null || child.signalCode !== null) return true
    return killTree(child.pid, { graceMs })
  }
}

module.exports = { Sidecar, SidecarError, killTree, cleanupStale, killStaleMongod, descendants, pidAlive }
