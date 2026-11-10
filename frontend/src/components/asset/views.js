/**
 * 场景视角（与后端 core/scene_views.py 口径一致）：
 * 一个场景 = 描述 description + 剧情状态 state_note + 若干视角 views[{ name, camera, image_path }]，每个视角一张无人场景图。
 * 后端列表接口已保证 views 至少 1 个（旧数据返回“默认视角”，图 = image_path），
 * 这里只做展示与编辑用的纯函数，组件和页面不各自解析。
 */
export const SINGLE_VIEW_NAME = '默认视角'
export const STATE_NOTE_MAX = 40
export const CAMERA_MAX = 30

/** 视角列表（至少 1 个）：接口没给 views 的旧数据按单视角兜底 */
export function sceneViews(item) {
  const views = Array.isArray(item && item.views) ? item.views.filter(v => v && (v.name || v.camera)) : []
  if (views.length) return views
  return [{ name: SINGLE_VIEW_NAME, camera: '', image_path: (item && item.image_path) || null }]
}

export function isSingleView(item) {
  return sceneViews(item).length <= 1
}

/** 某个视角的图（第一视角回退到 item.image_path） */
export function viewImage(item, index) {
  const views = sceneViews(item)
  const v = views[index] || views[0]
  return (v && v.image_path) || (index === 0 || !views[index] ? item.image_path : '') || ''
}

/** 批量出图待办：[{ item, formIndex, label }]（formIndex 在页面里统一表示“形态/视角下标”） */
export function viewJobs(items, missingOnly) {
  const jobs = []
  ;(items || []).forEach(item => {
    sceneViews(item).forEach((v, i) => {
      if (missingOnly && viewImage(item, i)) return
      jobs.push({ item, formIndex: i, label: isSingleView(item) ? item.name : `${item.name}·${v.name || SINGLE_VIEW_NAME}` })
    })
  })
  return jobs
}

/** 保存前整理：空视角丢掉，机位截到 30 字；至少保留一个 */
export function cleanViews(views) {
  const out = (views || [])
    .map(v => ({
      name: String(v.name || '').trim(),
      camera: String(v.camera || '').trim().slice(0, CAMERA_MAX),
      image_path: v.image_path || null
    }))
    .filter(v => v.name || v.camera)
    .map((v, i) => ({ ...v, name: v.name || `视角${i + 1}` }))
  return out.length ? out : [{ name: SINGLE_VIEW_NAME, camera: '', image_path: null }]
}

/** 编辑态草稿 */
export function viewDrafts(item) {
  return sceneViews(item).map(v => ({ name: v.name || '', camera: v.camera || '', image_path: v.image_path || null }))
}
