'use strict'
const fs = require('fs')
const path = require('path')

// 滚动日志：当前文件 name，超过 maxBytes 就轮转为 name.1 … name.keep（最旧的丢弃）。
class RotatingLog {
  constructor(dir, name = 'shell-backend.log', { maxBytes = 10 * 1024 * 1024, keep = 5 } = {}) {
    this.dir = dir
    this.name = name
    this.maxBytes = maxBytes
    this.keep = keep
    this.file = path.join(dir, name)
    fs.mkdirSync(dir, { recursive: true })
    this.size = 0
    try { this.size = fs.statSync(this.file).size } catch (_) { /* 新文件 */ }
    this.fd = null
  }

  _open() {
    if (this.fd === null) this.fd = fs.openSync(this.file, 'a', 0o600)
  }

  _rotate() {
    if (this.fd !== null) { fs.closeSync(this.fd); this.fd = null }
    const p = i => path.join(this.dir, `${this.name}.${i}`)
    try { fs.unlinkSync(p(this.keep)) } catch (_) { /* 没有 */ }
    for (let i = this.keep - 1; i >= 1; i--) {
      try { fs.renameSync(p(i), p(i + 1)) } catch (_) { /* 没有 */ }
    }
    try { fs.renameSync(this.file, p(1)) } catch (_) { /* 没有 */ }
    this.size = 0
  }

  write(text) {
    const data = Buffer.from(text.endsWith('\n') ? text : text + '\n', 'utf8')
    if (this.size > 0 && this.size + data.length > this.maxBytes) this._rotate()
    this._open()
    fs.writeSync(this.fd, data)
    this.size += data.length
  }

  close() {
    if (this.fd !== null) { try { fs.closeSync(this.fd) } catch (_) { /* ignore */ } this.fd = null }
  }
}

module.exports = { RotatingLog }
