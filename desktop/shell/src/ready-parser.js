'use strict'
// 解析后端 stdout：容忍 ready 之前的其他输出、JSON 行被拆成多个分片、前后有杂音。
// 同时负责日志脱敏：令牌不能落盘。

const REDACTED = '<redacted>'

/** 尝试把一行解析成 ready 事件；不是 ready 行返回 null */
function parseReadyLine(line) {
  const s = String(line).trim()
  const start = s.indexOf('{')
  const end = s.lastIndexOf('}')
  if (start < 0 || end <= start) return null
  let obj
  try { obj = JSON.parse(s.slice(start, end + 1)) } catch (_) { return null }
  if (!obj || obj.event !== 'ready') return null
  const port = Number(obj.port)
  if (!Number.isInteger(port) || port < 1 || port > 65535) return null
  if (typeof obj.token !== 'string' || !obj.token) return null
  return { port, token: obj.token }
}

/** 脱敏：已知令牌值整体替换；任意 "token":"..." 字段也替换 */
function redact(line, token) {
  let out = String(line)
  if (token) out = out.split(token).join(REDACTED)
  return out.replace(/("token"\s*:\s*")[^"]*(")/g, `$1${REDACTED}$2`)
}

/** 按行切分的流式解析器：feed(chunk) 返回本次凑齐的完整行 */
class LineSplitter {
  constructor() { this.buf = '' }
  feed(chunk) {
    this.buf += typeof chunk === 'string' ? chunk : chunk.toString('utf8')
    const parts = this.buf.split(/\r?\n/)
    this.buf = parts.pop()
    return parts
  }
  flush() {
    const rest = this.buf
    this.buf = ''
    return rest ? [rest] : []
  }
}

module.exports = { parseReadyLine, redact, LineSplitter, REDACTED }
