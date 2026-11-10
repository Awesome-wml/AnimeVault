// components/asset/views.js 单元测试：场景视角的兜底、出图待办、保存前整理（与后端 core/scene_views.py 一致）
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { SINGLE_VIEW_NAME, sceneViews, viewImage, viewJobs, cleanViews, viewDrafts } from '../../src/components/asset/views.js'

const multi = {
  name: '山神古庙', image_path: 'a.png',
  views: [{ name: '门口视角', camera: '朝里', image_path: 'a.png' }, { name: '供桌视角', camera: '朝门', image_path: null }]
}
const legacy = { name: '老场景', image_path: 'old.png' }

test('旧数据按单视角兜底，图取 image_path', () => {
  assert.deepEqual(sceneViews(legacy), [{ name: SINGLE_VIEW_NAME, camera: '', image_path: 'old.png' }])
  assert.equal(viewImage(legacy, 0), 'old.png')
})

test('按视角取图与出图待办', () => {
  assert.equal(viewImage(multi, 1), '')
  assert.deepEqual(viewJobs([multi, legacy], true).map(j => j.label), ['山神古庙·供桌视角'])
  assert.deepEqual(viewJobs([multi, legacy], false).map(j => [j.formIndex, j.label]), [[0, '山神古庙·门口视角'], [1, '山神古庙·供桌视角'], [0, '老场景']])
})

test('cleanViews 丢空项、机位截 30 字、至少一个', () => {
  const out = cleanViews([{ name: '', camera: 'x'.repeat(40) }, {}, { name: ' 高处 ', camera: '' }])
  assert.equal(out.length, 2)
  assert.equal(out[0].name, '视角1')
  assert.equal(out[0].camera.length, 30)
  assert.equal(out[1].name, '高处')
  assert.equal(cleanViews([]).length, 1)
  assert.equal(viewDrafts(multi).length, 2)
})
