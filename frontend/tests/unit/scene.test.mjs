// components/script/scene.js 单元测试：台词类型兜底与保存前整理（与后端 core/script_text.normalize_kind 一致）
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { NARRATOR, lineKind, kindLabel, sceneDraft, cleanDraft } from '../../src/components/script/scene.js'

test('lineKind：旁白一律 narration，缺省按说话人推断', () => {
  assert.equal(lineKind({ speaker: NARRATOR, kind: 'inner' }), 'narration')
  assert.equal(lineKind({ speaker: '陆川', kind: 'narration' }), 'narration')
  assert.equal(lineKind({ speaker: '陆川' }), 'onscreen')
  assert.equal(lineKind({ speaker: '陆川', kind: 'INNER' }), 'inner')
  assert.equal(lineKind({ speaker: '陆川', kind: 'bogus' }), 'onscreen')
  assert.equal(lineKind({}), 'narration')
  assert.equal(kindLabel('inner'), '心声')
  assert.equal(kindLabel('offscreen'), '画外')
})

test('sceneDraft / cleanDraft：保留 kind，旁白类型的说话人归为“旁白”，丢空台词', () => {
  const draft = sceneDraft({
    location: ' 包厢 ', time: '夜，内', characters: ['陆川'],
    dialogues: [{ speaker: '陆川', line: '我不甘心。', kind: 'inner' }, { speaker: '赵一帆', line: '停手吧。' }]
  })
  assert.deepEqual(draft.dialogues.map(d => d.kind), ['inner', 'onscreen'])
  draft.dialogues.push({ speaker: '陆川', line: '他走了。', kind: 'narration' }, { speaker: '陆川', line: '  ' })
  const fields = cleanDraft(draft)
  assert.equal(fields.location, '包厢')
  assert.deepEqual(fields.dialogues, [
    { speaker: '陆川', line: '我不甘心。', kind: 'inner' },
    { speaker: '赵一帆', line: '停手吧。', kind: 'onscreen' },
    { speaker: NARRATOR, line: '他走了。', kind: 'narration' }
  ])
})
