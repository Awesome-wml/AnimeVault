// components/shot/resplitText.js resplitMessage：覆盖重拆提示必须如实说明删多少、多少已出视频（后端 shot.py 是 delete_many 覆盖）
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { resplitMessage } from '../../src/components/shot/resplitText.js'

test('没有镜头时不提示', () => {
  assert.equal(resplitMessage([]), '')
})

test('有镜头时说明删除数量与已出视频数量，且不再说“追加”', () => {
  const msg = resplitMessage([{ video_path: 'videos/a.mp4' }, {}, { video_path: '' }], '“第1集”')
  assert.match(msg, /删除“第1集”现有的 3 个镜头/)
  assert.match(msg, /其中 1 个已出视频/)
  assert.match(msg, /不能撤销/)
  assert.doesNotMatch(msg, /追加/)
})

test('没有视频时不提额度', () => {
  const msg = resplitMessage([{}, {}])
  assert.doesNotMatch(msg, /额度/)
})
