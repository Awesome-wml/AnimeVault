// components/prompt/prompt-state.js 单元测试：内置 / 覆盖内置 的行状态、操作与提交载荷
import { test } from 'node:test'
import assert from 'node:assert/strict'
import {
  promptFlags, promptRowNote, promptActions, newPromptDraft, validatePrompt, promptPayload
} from '../../src/components/prompt/prompt-state.js'

test('promptFlags / promptRowNote：内置、代码有新版本、自定义默认覆盖内置', () => {
  assert.deepEqual(promptFlags({ is_builtin: true }), { builtin: true, hasUpdate: false, overriding: false })
  assert.deepEqual(promptFlags({ is_builtin: true, has_update: true, is_default: true }),
    { builtin: true, hasUpdate: true, overriding: false })
  assert.deepEqual(promptFlags({ is_default: true }), { builtin: false, hasUpdate: false, overriding: true })
  assert.deepEqual(promptFlags({ has_update: true }), { builtin: false, hasUpdate: false, overriding: false })
  assert.equal(promptRowNote({ is_builtin: true, has_update: true }), '代码已有新版本，可恢复内置')
  assert.equal(promptRowNote({ is_default: true }), '正在覆盖内置（默认）')
  assert.equal(promptRowNote({ is_builtin: true }), '')
  assert.equal(promptRowNote({}), '')
})

test('promptActions：内置行 查看/复制/恢复；自定义行 编辑/设为默认/复制/删除', () => {
  assert.deepEqual(promptActions({ is_builtin: true, has_update: true }), ['edit', 'duplicate', 'restore'])
  assert.deepEqual(promptActions({}), ['edit', 'set-default', 'duplicate', 'delete'])
  assert.deepEqual(promptActions({ is_default: true }), ['edit', 'duplicate', 'delete'])
})

test('newPromptDraft / validatePrompt：新建草稿与保存前校验', () => {
  assert.deepEqual(newPromptDraft('novel'), { name: '', version: 'v1.0', type: 'novel', category: '通用', content: '' })
  assert.equal(validatePrompt(newPromptDraft()), '请填写名称、类型和内容')
  assert.equal(validatePrompt({ name: 'a', type: 'novel', content: '  ' }), '请填写名称、类型和内容')
  assert.equal(validatePrompt({ name: 'a', type: 'novel', content: 'x' }), '')
  assert.equal(validatePrompt({ is_builtin: true, content: '' }), '内容不能为空')
  assert.equal(validatePrompt({ is_builtin: true, content: 'x' }), '')
})

test('promptPayload：内置只提交 content，自定义只提交表单字段', () => {
  assert.deepEqual(promptPayload({ _id: '1', is_builtin: true, name: '内置', content: 'c', has_update: true }), { content: 'c' })
  assert.deepEqual(
    promptPayload({ _id: '2', name: 'n', type: 'novel', category: '玄幻', version: 'v2', content: 'c', is_default: true, created_at: 'x' }),
    { name: 'n', type: 'novel', category: '玄幻', version: 'v2', content: 'c', is_default: true }
  )
  assert.deepEqual(promptPayload(newPromptDraft('novel')),
    { name: '', type: 'novel', category: '通用', version: 'v1.0', content: '' })
})
