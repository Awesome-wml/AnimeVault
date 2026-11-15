/**
 * 基于 fetch 的 SSE 读取（取代 EventSource）。
 * EventSource 不能带自定义请求头，桌面模式的本地令牌（X-DongAI-Local-Token）和用户 JWT
 * （Authorization）都带不上；fetch 流可以，且支持 POST、AbortController 取消。
 *
 *   streamSSE(url, { method, headers, body, signal, onOpen, onMessage, onError, onClose, fetchImpl })
 *     onMessage(data, { event, id })  每个事件一次，data 为原始字符串（多行 data: 以 \n 连接）；
 *                                     返回 false 表示不再继续读取（等同 EventSource.close）
 *     onError(err)                    HTTP 非 2xx（err.status、err.detail）、网络错误、读取中断；至多一次
 *     onClose()                       服务端正常结束流（对应 EventSource 断线前的最后状态）
 *   主动取消（signal.abort()）不触发 onError / onClose。
 *   返回 Promise，流结束、出错或取消后 resolve，不会 reject。
 */

/** 逐块喂入文本，吐出完整事件：按 \r\n / \n / \r 分行，空行结束一个事件，: 开头的注释行忽略 */
export function createSSEParser(onEvent) {
  let buffer = ''
  let data = []
  let event = ''
  let id = ''
  let skipLF = false

  function dispatch() {
    if (data.length) onEvent({ data: data.join('\n'), event: event || 'message', id })
    data = []
    event = ''
  }

  function line(l) {
    if (l === '') return dispatch()
    if (l[0] === ':') return
    const i = l.indexOf(':')
    const field = i === -1 ? l : l.slice(0, i)
    let value = i === -1 ? '' : l.slice(i + 1)
    if (value[0] === ' ') value = value.slice(1)
    if (field === 'data') data.push(value)
    else if (field === 'event') event = value
    else if (field === 'id') id = value
  }

  return {
    push(text) {
      buffer += text
      let start = 0
      for (let i = 0; i < buffer.length; i++) {
        const c = buffer[i]
        if (skipLF && i === start && c === '\n') { start = i + 1; skipLF = false; continue }
        skipLF = false
        if (c === '\n') { line(buffer.slice(start, i)); start = i + 1 } else if (c === '\r') {
          line(buffer.slice(start, i)); start = i + 1
          if (buffer[i + 1] === '\n') { i++; start = i + 1 } else if (i + 1 >= buffer.length) skipLF = true
        }
      }
      buffer = buffer.slice(start)
    }
  }
}

async function readErrorDetail(resp) {
  try {
    const body = await resp.json()
    let detail = body && body.detail
    if (Array.isArray(detail)) detail = detail.map(d => d.msg || JSON.stringify(d)).join('；')
    return typeof detail === 'string' ? detail : (detail ? JSON.stringify(detail) : '')
  } catch (_) {
    return ''
  }
}

export async function streamSSE(url, opts = {}) {
  const { method = 'GET', headers = {}, body, signal, onOpen, onMessage, onError, onClose } = opts
  const doFetch = opts.fetchImpl || (typeof fetch !== 'undefined' ? fetch : undefined)
  const aborted = () => !!(signal && signal.aborted)
  const fail = err => { if (!aborted() && onError) onError(err) }

  let resp
  try {
    resp = await doFetch(url, {
      method,
      headers: { Accept: 'text/event-stream', ...headers },
      body,
      signal
    })
  } catch (e) {
    return fail(e)
  }
  if (!resp.ok) {
    const detail = await readErrorDetail(resp)
    const err = new Error(detail || `请求失败（${resp.status}）`)
    err.status = resp.status
    err.detail = detail
    return fail(err)
  }
  if (onOpen) onOpen(resp)

  let stopped = false
  const parser = createSSEParser(evt => {
    if (stopped || aborted()) return
    if (onMessage && onMessage(evt.data, { event: evt.event, id: evt.id }) === false) stopped = true
  })
  const decoder = new TextDecoder()
  const reader = resp.body.getReader()
  try {
    for (;;) {
      const { value, done } = await reader.read()
      if (done) break
      parser.push(decoder.decode(value, { stream: true }))
      if (stopped) {
        try { await reader.cancel() } catch (_) { /* 已断开 */ }
        return
      }
    }
    parser.push(decoder.decode())
  } catch (e) {
    return fail(e)
  }
  if (!aborted() && onClose) onClose()
}
