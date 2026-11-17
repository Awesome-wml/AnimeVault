// 授权模式账号守卫的纯逻辑（utils/accountMode.js）
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { resolveAccountRoute, createSessionOpener, isLocalSessionMode, canOpenSession } from '../../src/utils/accountMode.js'

const st = (state, local_session = true) => ({ state, local_session })
const base = { toPath: '/home', isPublic: false, guestOnly: false, hasToken: false }

test('非授权模式：不介入，保持原登录流程', () => {
  assert.equal(resolveAccountRoute({ ...base, status: st('valid', false) }), null)
  assert.equal(resolveAccountRoute({ ...base, status: st('unactivated', false) }), null)
  assert.equal(resolveAccountRoute({ ...base, status: null }), null)
  assert.equal(isLocalSessionMode(null), false)
})

test('授权模式 + 已激活：无 token 先换会话再进首页', () => {
  assert.deepEqual(resolveAccountRoute({ ...base, status: st('valid') }), { redirect: null, needSession: true })
  assert.deepEqual(resolveAccountRoute({ ...base, status: st('grace'), hasToken: true }), { redirect: null, needSession: false })
})

test('授权模式 + 只读状态也能拿会话（查看已有数据）', () => {
  for (const s of ['expired', 'suspended', 'lease_expired']) {
    assert.equal(canOpenSession(st(s)), true)
    assert.deepEqual(resolveAccountRoute({ ...base, status: st(s) }), { redirect: null, needSession: true })
  }
})

test('授权模式：登录/注册/落地页重定向首页', () => {
  for (const p of ['/login', '/register']) {
    const r = resolveAccountRoute({ ...base, toPath: p, isPublic: true, guestOnly: true, status: st('valid'), hasToken: true })
    assert.deepEqual(r, { redirect: '/home', needSession: false })
  }
  const landing = resolveAccountRoute({ ...base, toPath: '/', isPublic: true, guestOnly: true, status: st('valid') })
  assert.deepEqual(landing, { redirect: '/home', needSession: true })
})

test('授权模式 + 未激活等状态：不换会话，只能去激活页', () => {
  for (const s of ['unactivated', 'invalid', 'machine_mismatch', 'revoked', 'session_conflict', 'clock_rollback']) {
    assert.equal(canOpenSession(st(s)), false)
    assert.deepEqual(resolveAccountRoute({ ...base, status: st(s) }), { redirect: '/activate', needSession: false })
    assert.deepEqual(resolveAccountRoute({ ...base, toPath: '/activate', isPublic: true, status: st(s) }), { redirect: null, needSession: false })
    assert.deepEqual(resolveAccountRoute({ ...base, toPath: '/login', isPublic: true, guestOnly: true, status: st(s) }), { redirect: '/activate', needSession: false })
  }
})

test('会话获取：成功存 token、并发合并、失败返回 null', async () => {
  let calls = 0
  let saved = null
  let user = null
  const open = createSessionOpener({
    fetchSession: async () => { calls++; return { data: { token: 't1', user: { id: 'u' } } } },
    saveToken: t => { saved = t },
    onUser: u => { user = u }
  })
  const [a, b] = await Promise.all([open(), open()])
  assert.equal(a, 't1'); assert.equal(b, 't1')
  assert.equal(calls, 1); assert.equal(saved, 't1'); assert.deepEqual(user, { id: 'u' })

  let saved2 = null
  const bad = createSessionOpener({ fetchSession: async () => { throw new Error('403') }, saveToken: t => { saved2 = t } })
  assert.equal(await bad(), null)
  assert.equal(saved2, null)
  const empty = createSessionOpener({ fetchSession: async () => ({ data: {} }), saveToken: t => { saved2 = t } })
  assert.equal(await empty(), null)
})
