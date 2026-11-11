/**
 * 风格库（媒介 + 题材）的纯函数：查找、旧 style 兼容映射、显示名与请求字段。
 * 来源 backend/core/style_library.py；项目保存 medium（媒介 id）+ genre（题材键文本），
 * 旧项目只有 style（7 个旧风格 id）时按 legacy_styles 映射为 3D 国漫 + 原题材。
 * 请求库数据用 styleLoader.js 的 loadStyleLibrary（这里不引 api，方便单元测试）。
 */

export const EMPTY_LIBRARY = { medium_groups: [], mediums: [], genres: [], default_medium: 'cg3d', fallback_medium: 'realistic', legacy_styles: {} }

/** 媒介 id → 媒介；传大类 id（2d）时取该类第一个子风格 */
export function findMedium(lib, id) {
  if (!id) return null
  const hit = lib.mediums.find(m => m.id === id)
  if (hit) return hit
  const group = lib.medium_groups.find(g => g.id === id)
  return group && group.mediums.length ? findMedium(lib, group.mediums[0].id) : null
}

/** 媒介所属的大类 */
export function mediumGroup(lib, mediumId) {
  const m = findMedium(lib, mediumId)
  return m ? lib.medium_groups.find(g => g.id === m.group) || null : null
}

/** 题材文本（id / 名称 / 题材键）→ 题材 */
export function findGenre(lib, text) {
  if (!text) return null
  return lib.genres.find(g => g.id === text || g.name === text || g.genre === text) || null
}

/** 作品当前的媒介与题材：新字段优先，旧 style 映射为 3D 国漫 + 原题材 */
export function projectStyle(lib, project) {
  const p = project || {}
  let medium = findMedium(lib, p.medium)
  let genre = findGenre(lib, p.genre)
  const legacyGenre = p.style && lib.legacy_styles[p.style]
  if (legacyGenre) {
    if (!medium) medium = findMedium(lib, lib.default_medium)
    if (!genre) genre = findGenre(lib, legacyGenre)
  }
  return { medium, genre }
}

/** 显示名：“真人实拍 · 家庭伦理” */
export function styleLabel(lib, project) {
  const { medium, genre } = projectStyle(lib, project)
  return [medium, genre].filter(Boolean).map(x => x.name).join(' · ')
}

/** 发给提取 / 出图接口的风格字段（只用项目当前的媒介与题材） */
export function styleFields(lib, project) {
  const { medium, genre } = projectStyle(lib, project)
  return { medium: medium ? medium.id : '', genre: genre ? genre.genre : '' }
}
