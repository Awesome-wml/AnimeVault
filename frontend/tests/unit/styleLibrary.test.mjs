// components/project/styleLibrary.js 单元测试：媒介 / 题材查找、旧 style 兼容映射、提取与出图字段（与后端 core/style_library.py 一致）
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { findMedium, findGenre, mediumGroup, projectStyle, styleLabel, styleFields, EMPTY_LIBRARY } from '../../src/components/project/styleLibrary.js'

const lib = {
  ...EMPTY_LIBRARY,
  medium_groups: [
    { id: 'realistic', name: '真人实拍', mediums: [{ id: 'realistic', name: '真人实拍' }] },
    { id: 'cg3d', name: '3D 国漫', mediums: [{ id: 'cg3d', name: '3D 国漫' }] },
    { id: '2d', name: '2D 动漫', mediums: [{ id: '2d_gufeng', name: '古风厚涂' }, { id: '2d_cel', name: '日系赛璐璐' }] }
  ],
  mediums: [
    { id: 'realistic', group: 'realistic', name: '真人实拍' }, { id: 'cg3d', group: 'cg3d', name: '3D 国漫' },
    { id: '2d_gufeng', group: '2d', name: '古风厚涂' }, { id: '2d_cel', group: '2d', name: '日系赛璐璐' }
  ],
  genres: [
    { id: 'xuanhuan', name: '玄幻', genre: '玄幻' }, { id: 'jiating', name: '家庭伦理', genre: '家庭伦理' },
    { id: 'zhichang', name: '现实职场', genre: '职场' }
  ],
  legacy_styles: { xuanhuan: 'xuanhuan' }
}

test('findMedium：按 id 找，大类 id 取第一个子画风，找不到为 null', () => {
  assert.equal(findMedium(lib, 'realistic').name, '真人实拍')
  assert.equal(findMedium(lib, '2d').id, '2d_gufeng')
  assert.equal(findMedium(lib, ''), null)
  assert.equal(findMedium(lib, 'nope'), null)
  assert.equal(mediumGroup(lib, '2d_cel').id, '2d')
})

test('findGenre：id / 名称 / 题材键都能命中', () => {
  assert.equal(findGenre(lib, 'zhichang').id, 'zhichang')
  assert.equal(findGenre(lib, '现实职场').id, 'zhichang')
  assert.equal(findGenre(lib, '职场').id, 'zhichang')
  assert.equal(findGenre(lib, '韩剧'), null)
})

test('projectStyle：新字段优先，旧 style 映射为 3D 国漫 + 原题材', () => {
  assert.deepEqual(styleFields(lib, { medium: 'realistic', genre: '家庭伦理' }), { medium: 'realistic', genre: '家庭伦理' })
  assert.equal(styleLabel(lib, { medium: '2d_cel', genre: '职场' }), '日系赛璐璐 · 现实职场')
  // 旧项目：只有 style
  assert.deepEqual(styleFields(lib, { style: 'xuanhuan' }), { medium: 'cg3d', genre: '玄幻' })
  assert.equal(styleLabel(lib, { style: 'xuanhuan' }), '3D 国漫 · 玄幻')
  // 旧项目：style + 自己的题材，题材以项目的为准
  assert.deepEqual(styleFields(lib, { style: 'xuanhuan', genre: '家庭伦理' }), { medium: 'cg3d', genre: '家庭伦理' })
  // 只有题材没有媒介：不替用户选媒介
  assert.deepEqual(styleFields(lib, { genre: '玄幻' }), { medium: '', genre: '玄幻' })
  assert.equal(styleLabel(lib, null), '')
  const { medium, genre } = projectStyle(lib, { style: 'unknown_custom' })
  assert.equal(medium, null); assert.equal(genre, null)
})
