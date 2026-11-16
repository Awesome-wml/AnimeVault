// utils/time.js、utils/session.js、utils/validators.js
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { endOfDaySeconds, isBeforeToday, formatTime } from '../../src/utils/time.js'
import { saveSession, loadSession, clearSession, isExpired } from '../../src/utils/session.js'
import { passwordError, usernameError } from '../../src/utils/validators.js'

test('到期日期不能早于今天，今天本身可以', () => {
  const now = new Date(2026, 10, 15, 15, 30)
  assert.equal(isBeforeToday(new Date(2026, 10, 14, 23, 59), now), true)
  assert.equal(isBeforeToday(new Date(2026, 10, 15, 0, 0), now), false)
  assert.equal(isBeforeToday(new Date(2026, 10, 16), now), false)
})

test('日期转到期 Unix 秒：当天 23:59:59（本地）', () => {
  const sec = endOfDaySeconds(new Date(2026, 10, 15, 8, 0))
  const d = new Date(sec * 1000)
  assert.deepEqual([d.getFullYear(), d.getMonth(), d.getDate(), d.getHours(), d.getMinutes(), d.getSeconds()], [2026, 10, 15, 23, 59, 59])
})

test('formatTime', () => {
  assert.equal(formatTime(0), '-')
  const s = Math.floor(new Date(2026, 0, 2, 3, 4).getTime() / 1000)
  assert.equal(formatTime(s), '2026-01-02 03:04')
  assert.equal(formatTime(s, false), '2026-01-02')
})

function memStorage() {
  const m = new Map()
  return { getItem: k => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, String(v)), removeItem: k => m.delete(k) }
}

test('会话：未过期可读，过期自动清除', () => {
  const st = memStorage()
  saveSession({ token: 't', expires_at: 2000, admin: { username: 'a' } }, st)
  assert.equal(loadSession(st, 1000).token, 't')
  assert.equal(loadSession(st, 2000), null)
  assert.equal(loadSession(st, 1000), null)   // 已被清掉
})

test('会话：损坏数据返回 null；clear 后为空', () => {
  const st = memStorage()
  st.setItem('dongai_license_admin_session', '{bad')
  assert.equal(loadSession(st, 1), null)
  saveSession({ token: 't', expires_at: 9e9 }, st)
  clearSession(st)
  assert.equal(loadSession(st, 1), null)
  assert.equal(isExpired(null), true)
})

test('密码至少 12 位、用户名格式', () => {
  assert.match(passwordError('short'), /12/)
  assert.equal(passwordError('a'.repeat(12)), '')
  assert.ok(passwordError(''))
  assert.equal(usernameError('alice.ops'), '')
  assert.ok(usernameError('A'))
  assert.ok(usernameError('ab'))
})
