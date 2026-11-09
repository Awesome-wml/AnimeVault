/** 作品相关的文案与常量（首页、全部作品共用） */

export const GENRES = ['玄幻', '都市', '仙侠', '末世', '古风', '悬疑', '搞笑', '韩剧']

/** 卡片下方的一行说明：题材 · 小说字数 / 还没有内容（只用真实字段） */
export function projectMeta(project) {
  const parts = []
  if (project.genre) parts.push(project.genre)
  const words = project.novel_content ? project.novel_content.length : 0
  parts.push(words ? `小说 ${words.toLocaleString('zh-CN')} 字` : '还没有内容')
  return parts.join(' · ')
}

/** 进入作品时去哪一页：没有小说先写小说，有小说去分镜 */
export function projectEntry(project) {
  const page = project.novel_content ? 'shots' : 'novel'
  return `/projects/${project.id}/${page}`
}

/** 后端 create_time 无时区（UTC），按 UTC 解析后再排序 */
export function createdAt(project) {
  const t = project.create_time
  if (!t) return 0
  const s = typeof t === 'string' && !/[zZ]|[+-]\d\d:?\d\d$/.test(t) ? t + 'Z' : t
  return new Date(s).getTime() || 0
}
