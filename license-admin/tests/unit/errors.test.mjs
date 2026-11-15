// utils/errors.js：后端 code -> 中文提示
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { mapError, ERROR_MESSAGES, formatWait } from '../../src/utils/errors.js'

test('后端约定的错误码都有中文映射', () => {
  const codes = ['LOGIN_FAILED', 'LOGIN_LOCKED', 'FORBIDDEN', 'UNAUTHENTICATED', 'INVALID_TRANSITION', 'MACHINE_CODE_INVALID',
    'MACHINE_CODE_TOO_FEW', 'EXPIRES_IN_PAST', 'PLAN_INVALID', 'LAST_SUPER', 'USERNAME_EXISTS']
  for (const c of codes) {
    assert.ok(ERROR_MESSAGES[c] && /[一-龥]/.test(ERROR_MESSAGES[c]), c)
    assert.equal(mapError({ status: 400, data: { code: c, message: 'english' } }).message.includes('english'), false, c)
  }
})

test('按 code 返回固定中文，不使用服务端英文 message', () => {
  const e = mapError({ status: 409, data: { code: 'INVALID_TRANSITION', message: 'status is x', status: 'pending' } })
  assert.equal(e.code, 'INVALID_TRANSITION')
  assert.equal(e.status, 409)
  assert.match(e.message, /状态/)
})

test('LOGIN_LOCKED 带剩余等待时间', () => {
  const e = mapError({ status: 429, data: { code: 'LOGIN_LOCKED', message: 'x', retry_after: 600 } })
  assert.equal(e.retryAfter, 600)
  assert.match(e.message, /锁定/)
  assert.match(e.message, /10 分钟/)
  assert.equal(mapError({ status: 429, data: { code: 'LOGIN_LOCKED' } }).retryAfter, 0)
})

test('formatWait：不足一分钟按秒，其余向上取整到分钟', () => {
  assert.equal(formatWait(45), '45 秒')
  assert.equal(formatWait(60), '1 分钟')
  assert.equal(formatWait(61), '2 分钟')
  assert.equal(formatWait(0), '1 秒')
})

test('VALIDATION_ERROR 带出字段名', () => {
  const e = mapError({ status: 422, data: { code: 'VALIDATION_ERROR', fields: ['expires_at', 'plan'] } })
  assert.match(e.message, /expires_at、plan/)
})

test('未收录的 code：中文 message 直接用，英文走状态码兜底', () => {
  assert.equal(mapError({ status: 422, data: { code: 'NEW_ONE', message: '新的中文错误' } }).message, '新的中文错误')
  assert.equal(mapError({ status: 403, data: { code: 'NEW_ONE', message: 'nope' } }).message, '没有权限执行此操作')
  assert.equal(mapError({ status: 418, data: null }).message, '操作失败')
})

test('5xx 与断网', () => {
  assert.match(mapError({ status: 500, data: { detail: 'boom' } }).message, /内部错误/)
  const n = mapError({ networkError: true })
  assert.equal(n.code, 'NETWORK_ERROR')
  assert.match(n.message, /无法连接/)
})
