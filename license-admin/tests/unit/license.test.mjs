// utils/license.js：状态机按钮可用性、到期高亮、最近在线文案、事件摘要
import { test } from 'node:test'
import assert from 'node:assert/strict'
import {
  availableActions, disabledReason, expiryLevel, lastSeenText, statusMeta, eventSummary, DAY,
  operatorName, kickDisabledReason, unbindDisabledReason, deviceStateMeta, requestStatusMeta, canHandleRequest,
  eventLabel, AUDIT_ACTION_LABELS
} from '../../src/utils/license.js'

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

test('操作人展示：有用户名用用户名，历史记录用 id 前 8 位兜底，都没有返回空串', () => {
  assert.equal(operatorName('oper', 'abcdef0123456789'), 'oper')
  assert.equal(operatorName(null, 'abcdef0123456789'), 'abcdef01')
  assert.equal(operatorName(undefined, undefined), '')
  assert.equal(operatorName('', null), '')
})

test('踢下线按钮：吊销和无在线会话时禁用并给原因，有会话的可用', () => {
  assert.match(kickDisabledReason({ status: 'revoked', active_sid: 'x' }), /吊销/)
  assert.match(kickDisabledReason({ status: 'active', active_sid: null }), /没有在线会话/)
  assert.match(kickDisabledReason({ status: 'pending', active_sid: null }), /没有在线会话/)
  assert.equal(kickDisabledReason({ status: 'active', active_sid: 'sid' }), '')
  assert.equal(kickDisabledReason({ status: 'suspended', active_sid: 'sid' }), '')
  assert.ok(kickDisabledReason(null))
})

test('解绑按钮：已吊销或已解绑的设备不可再解绑', () => {
  assert.match(unbindDisabledReason({ status: 'revoked' }, { bound: true }), /吊销/)
  assert.match(unbindDisabledReason({ status: 'active' }, { bound: false }), /已解绑/)
  assert.equal(unbindDisabledReason({ status: 'active' }, { bound: true }), '')
  assert.equal(unbindDisabledReason({ status: 'expired' }, { bound: true }), '')
})

test('设备状态：当前在线 / 已绑定 / 已解绑', () => {
  assert.equal(deviceStateMeta({ bound: true, is_current: true }).label, '当前在线')
  assert.equal(deviceStateMeta({ bound: true, is_current: false }).label, '已绑定')
  assert.equal(deviceStateMeta({ bound: false, is_current: false }).label, '已解绑')
  assert.equal(deviceStateMeta({ bound: false, is_current: true }).label, '已解绑')   // 已解绑优先
})

test('申请单状态与可处理判断：只有待处理的能签发或驳回', () => {
  assert.equal(requestStatusMeta('pending').label, '待处理')
  assert.equal(requestStatusMeta('issued').tone, 'green')
  assert.equal(requestStatusMeta('rejected').label, '已驳回')
  assert.equal(requestStatusMeta('x').label, 'x')
  assert.equal(canHandleRequest('pending'), true)
  assert.equal(canHandleRequest('issued'), false)
  assert.equal(canHandleRequest('rejected'), false)
})

test('新事件和审计动作有中文名；踢下线、解绑事件有摘要', () => {
  assert.equal(eventLabel('session_kicked'), '踢下线')
  assert.equal(eventLabel('device_unbound'), '解绑设备')
  assert.equal(AUDIT_ACTION_LABELS['request.issue'], '签发申请单')
  assert.match(eventSummary({ type: 'session_kicked', detail: { via: 'kick' } }), /重新激活/)
  assert.match(eventSummary({ type: 'session_kicked', detail: { via: 'unbind' } }), /解绑/)
  assert.match(eventSummary({ type: 'device_unbound', detail: { kicked: true } }), /下线/)
})
