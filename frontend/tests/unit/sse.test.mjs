// utils/sse.js：fetch 流式 SSE（取代 EventSource）
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { streamSSE, createSSEParser } from '../../src/utils/sse.js'

const enc = new TextEncoder()

/** 假 fetch：chunks 依次作为响应体分块；记录收到的请求参数 */
function fakeFetch({ status = 200, chunks = [], json, failAfter, reject } = {}) {
  const calls = []
  const impl = async (url, init) => {
    calls.push({ url, init })
    if (reject) throw reject
    let i = 0
    const body = new ReadableStream({
      async pull(ctrl) {
        if (init.signal && init.signal.aborted) { ctrl.error(new DOMException('aborted', 'AbortError')); return }
        if (failAfter !== undefined && i === failAfter) { ctrl.error(new Error('socket hang up')); return }
        if (i >= chunks.length) { ctrl.close(); return }
        ctrl.enqueue(enc.encode(chunks[i++]))
      }
    })
    return { ok: status >= 200 && status < 300, status, body, json: async () => { if (json === undefined) throw new Error('not json'); return json } }
  }
  impl.calls = calls
  return impl
}

function collect(opts) {
  const got = { messages: [], errors: [], closed: 0 }
  const p = streamSSE('/api/x', {
    ...opts,
    onMessage: (d, m) => { got.messages.push(d); if (opts.stopOn && d === opts.stopOn) return false },
    onError: e => got.errors.push(e),
    onClose: () => { got.closed++ }
  })
  return p.then(() => got)
}

test('data 行跨 chunk 拆分（含拆在 data: 中间、\\r\\n 换行）', async () => {
  const f = fakeFetch({ chunks: ['da', 'ta: {"type":"chu', 'nk","content":"你', '好"}\r\n\r', '\ndata: {"type":"done"}\n\n'] })
  const got = await collect({ fetchImpl: f })
  assert.deepEqual(got.messages, ['{"type":"chunk","content":"你好"}', '{"type":"done"}'])
  assert.equal(got.closed, 1)
  assert.deepEqual(got.errors, [])
})

test('中文被拆在 UTF-8 字节中间也能正确解码', async () => {
  const bytes = enc.encode('data: 你好\n\n')
  const f = async () => ({
    ok: true, status: 200,
    body: new ReadableStream({ start(c) { c.enqueue(bytes.slice(0, 8)); c.enqueue(bytes.slice(8)); c.close() } })
  })
  const got = await collect({ fetchImpl: f })
  assert.deepEqual(got.messages, ['你好'])
})

test('注释/ping、多行 data、event 名', async () => {
  const seen = []
  await streamSSE('/x', {
    fetchImpl: fakeFetch({ chunks: [': ping\n\nevent: foo\ndata: a\ndata: b\n\n'] }),
    onMessage: (d, m) => seen.push([d, m.event])
  })
  assert.deepEqual(seen, [['a\nb', 'foo']])
})

test('onMessage 返回 false：停止读取，不触发 onClose/onError（完成事件 [DONE]）', async () => {
  const f = fakeFetch({ chunks: ['data: 1\n\ndata: [DONE]\n\ndata: 3\n\n'] })
  const got = await collect({ fetchImpl: f, stopOn: '[DONE]' })
  assert.deepEqual(got.messages, ['1', '[DONE]'])
  assert.equal(got.closed, 0)
  assert.equal(got.errors.length, 0)
})

test('中途读取报错 -> onError，一次', async () => {
  const f = fakeFetch({ chunks: ['data: 1\n\n', 'data: 2\n\n'], failAfter: 1 })
  const got = await collect({ fetchImpl: f })
  assert.deepEqual(got.messages, ['1'])
  assert.equal(got.errors.length, 1)
  assert.match(got.errors[0].message, /socket hang up/)
  assert.equal(got.closed, 0)
})

test('网络错误（fetch reject）-> onError', async () => {
  const got = await collect({ fetchImpl: fakeFetch({ reject: new TypeError('Failed to fetch') }) })
  assert.equal(got.errors.length, 1)
  assert.equal(got.messages.length, 0)
})

test('取消：abort 后不再回调 onMessage/onError/onClose', async () => {
  const ctrl = new AbortController()
  const got = { m: [], e: 0, c: 0 }
  const f = fakeFetch({ chunks: ['data: 1\n\n', 'data: 2\n\n', 'data: 3\n\n'] })
  await streamSSE('/x', {
    fetchImpl: f, signal: ctrl.signal,
    onMessage: d => { got.m.push(d); ctrl.abort() },
    onError: () => got.e++, onClose: () => got.c++
  })
  assert.deepEqual(got.m, ['1'])
  assert.equal(got.e, 0)
  assert.equal(got.c, 0)
  assert.equal(f.calls[0].init.signal, ctrl.signal)
})

test('HTTP 非 200：错误体 detail 进 err.message，带 status', async () => {
  const got = await collect({ fetchImpl: fakeFetch({ status: 401, json: { detail: '本地令牌无效' } }) })
  assert.equal(got.errors[0].status, 401)
  assert.equal(got.errors[0].message, '本地令牌无效')
  const got2 = await collect({ fetchImpl: fakeFetch({ status: 502 }) })
  assert.equal(got2.errors[0].message, '请求失败（502）')
  const got3 = await collect({ fetchImpl: fakeFetch({ status: 422, json: { detail: [{ msg: 'a' }, { msg: 'b' }] } }) })
  assert.equal(got3.errors[0].message, 'a；b')
})

test('请求头、方法、请求体原样传给 fetch（含本地令牌头/不含）', async () => {
  const f = fakeFetch({ chunks: [] })
  await streamSSE('/api/x', {
    fetchImpl: f, method: 'POST', body: '{"a":1}',
    headers: { Authorization: 'Bearer jwt', 'X-DongAI-Local-Token': 'test-token', 'Content-Type': 'application/json' }
  })
  const { init } = f.calls[0]
  assert.equal(init.method, 'POST')
  assert.equal(init.body, '{"a":1}')
  assert.equal(init.headers['X-DongAI-Local-Token'], 'test-token')
  assert.equal(init.headers.Authorization, 'Bearer jwt')
  assert.equal(init.headers.Accept, 'text/event-stream')
  const g = fakeFetch({ chunks: [] })
  await streamSSE('/api/x', { fetchImpl: g })
  assert.equal(g.calls[0].init.method, 'GET')
  assert.equal('X-DongAI-Local-Token' in g.calls[0].init.headers, false)
})

test('解析器：\\r 单独换行、结尾无空行的残余事件不下发', () => {
  const out = []
  const p = createSSEParser(e => out.push(e.data))
  p.push('data: a\r\r')
  p.push('data: b\n')
  assert.deepEqual(out, ['a'])
})
