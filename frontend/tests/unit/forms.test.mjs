// components/asset/forms.js 单元测试：角色形态的展示、兜底与保存前整理（与后端 core/character_forms.py 一致）
import { test } from 'node:test'
import assert from 'node:assert/strict'
import {
  SINGLE_FORM_NAME, characterForms, isSingleForm, parseSceneNos, sceneNosText, formLabel,
  formImage, formJobs, hasMissingImage, cleanForms, formDrafts
} from '../../src/components/asset/forms.js'

const multi = {
  name: '周桂芳', image_path: 'images/f1.png',
  forms: [
    { name: '索财形态', outfit: '枣红上衣', scene_nos: [1, 2, 5], image_path: 'images/f1.png' },
    { name: '失态形态', outfit: '扣子崩开', scene_nos: [3, 4], image_path: null }
  ]
}
const legacy = { name: '甲', description: '三十岁男子，黑衬衫。', image_path: 'images/a.png' }

test('characterForms：旧数据按单形态兜底，穿搭取 description，图取 image_path', () => {
  assert.deepEqual(characterForms(legacy), [{ name: SINGLE_FORM_NAME, outfit: '三十岁男子，黑衬衫。', scene_nos: [], image_path: 'images/a.png' }])
  assert.equal(isSingleForm(legacy), true)
  assert.equal(isSingleForm(multi), false)
  assert.equal(characterForms({ name: '乙' })[0].outfit, '')
})

test('parseSceneNos / sceneNosText / formLabel', () => {
  assert.deepEqual(parseSceneNos('3，1、1 第5场'), [1, 3, 5])
  assert.deepEqual(parseSceneNos([2, '2', 0, 'x']), [2])
  assert.equal(sceneNosText([1, 3]), '第 1、3 场')
  assert.equal(sceneNosText([]), '场次未标')
  assert.equal(formLabel(multi.forms[1]), '失态形态 · 第 3、4 场')
})

test('formImage：按形态取图，第一形态回退到 image_path', () => {
  assert.equal(formImage(multi, 0), 'images/f1.png')
  assert.equal(formImage(multi, 1), '')
  assert.equal(formImage(legacy, 0), 'images/a.png')
  assert.equal(formImage({ name: '丙', forms: [{ name: 'A', outfit: 'x' }], image_path: 'images/c.png' }, 0), 'images/c.png')
})

test('formJobs / hasMissingImage：批量出图按形态展开，只补缺图的', () => {
  const all = formJobs([multi, legacy])
  assert.deepEqual(all.map(j => [j.item.name, j.formIndex, j.label]), [['周桂芳', 0, '周桂芳·索财形态'], ['周桂芳', 1, '周桂芳·失态形态'], ['甲', 0, '甲']])
  const missing = formJobs([multi, legacy], true)
  assert.deepEqual(missing.map(j => [j.item.name, j.formIndex]), [['周桂芳', 1]])
  assert.equal(hasMissingImage(multi), true)
  assert.equal(hasMissingImage(legacy), false)
})

test('formDrafts / cleanForms：草稿场次用文本，保存前转数组、丢空项、补名字', () => {
  const drafts = formDrafts(multi)
  assert.equal(drafts[0].scene_nos, '1、2、5')
  drafts[1].scene_nos = '4，3'
  drafts.push({ name: '', outfit: '', scene_nos: '' }, { name: '', outfit: '白衣', scene_nos: '7' })
  assert.deepEqual(cleanForms(drafts), [
    { name: '索财形态', outfit: '枣红上衣', scene_nos: [1, 2, 5], image_path: 'images/f1.png' },
    { name: '失态形态', outfit: '扣子崩开', scene_nos: [3, 4], image_path: null },
    { name: '形态3', outfit: '白衣', scene_nos: [7], image_path: null }
  ])
})
