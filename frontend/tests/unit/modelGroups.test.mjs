import test from 'node:test'
import assert from 'node:assert/strict'
import { buildModelOptions } from '../../src/components/novel/modelGroups.js'

const list = [
  { _id: 'a', name: 'Seedream 5.5 出图', provider: 'volcengine', is_default: true,
    models: ['doubao-seedream-5-5-261028'], model_kinds: { 'doubao-seedream-5-5-261028': 'image' } },
  { _id: 'b', name: '智谱对话', provider: 'zhipu', models: ['glm-5.3-flashx', 'glm-4.5-flash'],
    model_kinds: { 'glm-5.3-flashx': 'chat', 'glm-4.5-flash': 'chat' } },
  { _id: 'c', name: '智谱全家桶', provider: 'zhipu', models: ['glm-5', 'glm-image'],
    model_kinds: { 'glm-5': 'chat', 'glm-image': 'image' } }
]

test('文字环节和出图设置各列各的模型', () => {
  const o = buildModelOptions(list)
  assert.deepEqual(o.chatGroups.map(g => g.items.map(i => i.label)), [['glm-5.3-flashx', 'glm-4.5-flash'], ['glm-5']])
  assert.deepEqual(o.imageGroups.map(g => g.items.map(i => i.label)), [['doubao-seedream-5-5-261028'], ['glm-image']])
})

test('出图预设设为默认，不会变成文字环节的默认', () => {
  const o = buildModelOptions(list)
  assert.equal(o.chatDefaultKey, 'b::glm-5.3-flashx')
  assert.equal(o.imageDefaultLabel, 'Seedream 5.5 出图 · doubao-seedream-5-5-261028')
})

test('没设默认出图预设时不显示默认名（后端用账号设置）', () => {
  const o = buildModelOptions(list.map(m => ({ ...m, is_default: false })))
  assert.equal(o.imageDefaultLabel, '')
  assert.equal(o.chatDefaultKey, 'b::glm-5.3-flashx')
})

test('老后端没有 model_kinds 时按 model_type', () => {
  const o = buildModelOptions([
    { _id: 'x', name: 'x', models: ['m1'], model_type: 'image' },
    { _id: 'y', name: 'y', model: 'm2' }
  ])
  assert.deepEqual(o.imageGroups.map(g => g.id), ['x'])
  assert.deepEqual(o.chatGroups.map(g => g.id), ['y'])
  assert.deepEqual(buildModelOptions(null).chatGroups, [])
})
