// components/base/status.js：多段续接的显示口径（本场台词占比、段检查、接缝类型）
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { sceneFillStatus, checksStatus, jointLabel, statusInfo } from '../../src/components/base/status.js'

test('本场台词占比按后端给的状态上色', () => {
  assert.deepEqual(sceneFillStatus({ ratio: 0.454, status: 'ok' }), { key: 'scene_fill_ok', n: 45 })
  assert.deepEqual(sceneFillStatus({ ratio: 0.87, status: 'high' }), { key: 'scene_fill_high', n: 87 })
  assert.deepEqual(sceneFillStatus({ ratio: 0.2, status: 'low' }), { key: 'scene_fill_low', n: 20 })
  assert.equal(sceneFillStatus(null), null)
  assert.equal(statusInfo('scene_fill_high', 87).text, '本场台词 87%，偏满')
})

test('段检查：空列表是通过，旧数据没有检查', () => {
  assert.deepEqual(checksStatus([]), { key: 'seg_checks_ok', n: 0 })
  assert.deepEqual(checksStatus([{ code: 'long_line', msg: 'x' }, { code: 'tail_speech', msg: 'y' }]), { key: 'seg_checks_warn', n: 2 })
  assert.equal(checksStatus(undefined), null)
  assert.equal(statusInfo('seg_checks_warn', 2).text, '2 项提醒')
})

test('接缝类型：老数据按续接', () => {
  assert.equal(jointLabel('cut'), '切镜')
  assert.equal(jointLabel('continue'), '续接')
  assert.equal(jointLabel(undefined), '续接')
})
