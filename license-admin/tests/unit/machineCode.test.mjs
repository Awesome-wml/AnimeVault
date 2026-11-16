// utils/machineCode.js：粘贴后的格式初检（校验位以后端为准）
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { precheckMachineCode, normalizeMachineCode, groupMachineCode, VALID_LENGTHS } from '../../src/utils/machineCode.js'

// 3 个分量的真实形态：42 个字符，每 5 位一组
const body = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567ABCDEFGHIJ'.slice(0, 42)

test('合法长度表：2 个分量 30 位，3 个分量 42 位', () => {
  assert.equal(VALID_LENGTHS[30], 2)
  assert.equal(VALID_LENGTHS[42], 3)
  assert.equal(VALID_LENGTHS[17], 1)
})

test('去空白、换行、短横线并转大写；0->O 1->I', () => {
  assert.equal(normalizeMachineCode(' ab-cd\n ef_g0 1 '), 'ABCDEFGOI')
  assert.equal(groupMachineCode('ABCDEFGHIJK'), 'ABCDE-FGHIJ-K')
})

test('空输入：empty', () => {
  assert.equal(precheckMachineCode('  \n').level, 'empty')
})

test('长度合法且字符合法：ok，并给出分组格式和分量数', () => {
  const r = precheckMachineCode(body.toLowerCase().replace(/(.{5})/g, '$1 '))
  assert.equal(r.level, 'ok')
  assert.equal(r.components, 3)
  assert.equal(r.formatted, groupMachineCode(body))
  assert.equal(r.normalized, body)
})

test('字符不在 Base32 字符集（8、9、符号）：error 并指出字符', () => {
  const r = precheckMachineCode(body.slice(0, 40) + '89')
  assert.equal(r.level, 'error')
  assert.match(r.message, /8 9/)
  assert.equal(precheckMachineCode('ABC!DEF').level, 'error')
})

test('长度不对：区分太短和多余', () => {
  const short = precheckMachineCode(body.slice(0, 20))
  assert.equal(short.level, 'error')
  assert.match(short.message, /长度/)
  const long = precheckMachineCode(body + 'AAAAAAAAAAAA')
  assert.equal(long.level, 'error')
  assert.match(long.message, /长度/)
})

test('只有 1 个分量：error（服务端要求至少 2 个）', () => {
  const r = precheckMachineCode('ABCDEFGHIJKLMNOPQ')
  assert.equal(r.level, 'error')
  assert.equal(r.components, 1)
  assert.match(r.message, /不足 2 个/)
})
