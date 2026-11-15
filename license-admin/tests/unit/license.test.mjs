// utils/license.js：状态机按钮可用性、到期高亮、最近在线文案、事件摘要
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { availableActions, disabledReason, expiryLevel, lastSeenText, statusMeta, eventSummary, DAY } from '../../src/utils/license.js'

const on = status => Object.entries(availableActions(status)).filter(([, v]) => v).map(([k]) => k).sort()

test('状态机：每个状态允许的操作', () => {
  assert.deepEqual(on('pending'), ['extend', 'revoke'])        // pending 不能停用
  assert.deepEqual(on('active'), ['extend', 'revoke', 'suspend'])
  assert.deepEqual(on('suspended'), ['extend', 'resume', 'revoke'])
  assert.deepEqual(on('expired'), ['extend', 'revoke'])        // 延期后回到 active
  assert.deepEqual(on('revoked'), [])                          // 终态全禁用
  assert.deepEqual(on('unknown'), [])
})

test('不可用按钮有原因提示，可用的没有', () => {
  assert.match(disabledReason('pending', 'suspend'), /待激活/)
  assert.match(disabledReason('revoked', 'extend'), /吊销/)
  assert.match(disabledReason('active', 'resume'), /已停用/)
  assert.equal(disabledReason('active', 'suspend'), '')
})

test('状态颜色约定', () => {
  assert.equal(statusMeta('pending').tone, 'grey')
  assert.equal(statusMeta('active').tone, 'green')
  assert.equal(statusMeta('suspended').tone, 'orange')
  assert.equal(statusMeta('revoked').tone, 'red')
  assert.equal(statusMeta('expired').tone, 'dark')
})

test('到期高亮：7 天内 soon，已过期 expired，其余 normal', () => {
  const now = 1_700_000_000
  assert.equal(expiryLevel(now + 6 * DAY, 'active', now), 'soon')
  assert.equal(expiryLevel(now + 7 * DAY, 'active', now), 'soon')
  assert.equal(expiryLevel(now + 7 * DAY + 1, 'active', now), 'normal')
  assert.equal(expiryLevel(now - 1, 'active', now), 'expired')
  assert.equal(expiryLevel(now + DAY, 'pending', now), 'soon')
  assert.equal(expiryLevel(now + DAY, 'revoked', now), 'normal')   // 已吊销不提示
  assert.equal(expiryLevel(null, 'active', now), 'normal')
})

test('最近在线：未激活 / 从未在线 / 有时间', () => {
  const f = t => 'T' + t
  assert.equal(lastSeenText({ status: 'pending', last_seen_at: null }, f), '未激活')
  assert.equal(lastSeenText({ status: 'active', last_seen_at: null }, f), '从未在线')
  assert.equal(lastSeenText({ status: 'active', last_seen_at: 123 }, f), 'T123')
})

test('事件摘要', () => {
  const f = t => 'D' + t
  assert.equal(eventSummary({ type: 'extended', detail: { old_expires_at: 1, new_expires_at: 2 } }, f), '到期时间 D1 → D2')
  assert.equal(eventSummary({ type: 'suspended', detail: { from: 'active', to: 'suspended' } }, f), '正常 → 已停用')
  assert.equal(eventSummary({ type: 'issued', detail: { plan: 'pro', expires_at: 9 } }, f), '套餐 pro，到期 D9')
})
