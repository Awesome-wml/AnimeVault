/**
 * 角色形态（与后端 core/character_forms.py 口径一致）：
 * 一个角色 = 固定面部特征 face + 若干形态 forms[{ name, outfit, scene_nos, image_path }] + 音色描述 voice。
 * 后端列表接口已保证 forms 至少 1 个（旧数据返回“单形态”，穿搭 = description，图 = image_path），
 * 这里只做前端展示与编辑用的纯函数，组件和页面不各自解析。
 */
export const SINGLE_FORM_NAME = '单形态'

/** 形态列表（至少 1 个）：接口没给 forms 的旧数据按单形态兜底 */
export function characterForms(item) {
  const forms = Array.isArray(item && item.forms) ? item.forms.filter(f => f && (f.name || f.outfit)) : []
  if (forms.length) return forms
  return [{ name: SINGLE_FORM_NAME, outfit: (item && item.description) || '', scene_nos: [], image_path: (item && item.image_path) || null }]
}

/** 是否只有一个形态（卡片上显示“单形态”空状态） */
export function isSingleForm(item) {
  return characterForms(item).length <= 1
}

/** 场次数组 → 标签文字：“第 1、3 场”；空 → “场次未标” */
export function sceneNosText(nos) {
  const list = parseSceneNos(nos)
  return list.length ? `第 ${list.join('、')} 场` : '场次未标'
}

/** “1,3、5 / 第1场” 之类的输入 → 去重升序的正整数数组 */
export function parseSceneNos(value) {
  const raw = Array.isArray(value) ? value : String(value == null ? '' : value).split(/[,，、\s]+/)
  const out = []
  raw.forEach(v => {
    const n = parseInt(String(v).replace(/[^\d]/g, ''), 10)
    if (n > 0 && !out.includes(n)) out.push(n)
  })
  return out.sort((a, b) => a - b)
}

/** 标签文字：形态名 + 出现场次 */
export function formLabel(form) {
  return `${form.name || SINGLE_FORM_NAME} · ${sceneNosText(form.scene_nos)}`
}

/** 某个形态的图（旧数据第一形态回退到 item.image_path） */
export function formImage(item, index) {
  const forms = characterForms(item)
  const f = forms[index] || forms[0]
  return (f && f.image_path) || (index === 0 || !forms[index] ? item.image_path : '') || ''
}

/** 批量出图待办：[{ item, formIndex, label }]，missingOnly 只取还没有图的形态 */
export function formJobs(items, missingOnly) {
  const jobs = []
  ;(items || []).forEach(item => {
    characterForms(item).forEach((f, i) => {
      if (missingOnly && formImage(item, i)) return
      jobs.push({ item, formIndex: i, label: isSingleForm(item) ? item.name : `${item.name}·${f.name || SINGLE_FORM_NAME}` })
    })
  })
  return jobs
}

/** 角色是否还有缺图的形态 */
export function hasMissingImage(item) {
  return characterForms(item).some((f, i) => !formImage(item, i))
}

/** 保存前整理：空形态丢掉，场次转数组；至少保留一个 */
export function cleanForms(forms) {
  const out = (forms || [])
    .map(f => ({
      name: String(f.name || '').trim(),
      outfit: String(f.outfit || '').trim(),
      scene_nos: parseSceneNos(f.scene_nos),
      image_path: f.image_path || null
    }))
    .filter(f => f.name || f.outfit)
  return out.map((f, i) => ({ ...f, name: f.name || `形态${i + 1}` }))
}

/** 编辑态：把接口数据复制成可编辑草稿（场次用文本框输入） */
export function formDrafts(item) {
  return characterForms(item).map(f => ({
    name: f.name || '',
    outfit: f.outfit || '',
    scene_nos: parseSceneNos(f.scene_nos).join('、'),
    image_path: f.image_path || null
  }))
}
