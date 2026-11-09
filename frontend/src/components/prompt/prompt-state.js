/**
 * 提示词行的状态与表单草稿（纯函数，页面与表格组件共用）。
 * 后端取值顺序：指定 prompt_id → 题材用户默认 → 通用用户默认 → 内置记录 → 代码常量，
 * 所以“设为默认”的自定义提示词会覆盖同类型的内置提示词。
 */

/** 行状态：builtin 内置；hasUpdate 代码已有新版本（用户改过内置内容）；overriding 自定义默认正在覆盖内置 */
export function promptFlags(row) {
  const builtin = !!(row && row.is_builtin)
  return {
    builtin,
    hasUpdate: builtin && !!row.has_update,
    overriding: !builtin && !!(row && row.is_default)
  }
}

/** 行内提示文字（没有返回空串） */
export function promptRowNote(row) {
  const f = promptFlags(row)
  if (f.hasUpdate) return '代码已有新版本，可恢复内置'
  if (f.overriding) return '正在覆盖内置（默认）'
  return ''
}

/** 行可用的操作，按显示顺序 */
export function promptActions(row) {
  const f = promptFlags(row)
  if (f.builtin) return ['edit', 'duplicate', 'restore']
  const actions = ['edit']
  if (!row.is_default) actions.push('set-default')
  actions.push('duplicate', 'delete')
  return actions
}

/** 新建提示词的表单草稿 */
export function newPromptDraft(type = '', category = '通用') {
  return { name: '', version: 'v1.0', type, category, content: '' }
}

/** 保存前校验：返回错误文案，通过返回空串 */
export function validatePrompt(form) {
  if (!form) return '请填写名称、类型和内容'
  if (form.is_builtin) return (form.content || '').trim() ? '' : '内容不能为空'
  if (!form.name || !form.type || !(form.content || '').trim()) return '请填写名称、类型和内容'
  return ''
}

/** 内置提示词保存时只提交 content；自定义提交整条 */
export function promptPayload(form) {
  if (form.is_builtin) return { content: form.content }
  const { name, type, category, version, content, is_default } = form
  const payload = { name, type, category, version, content }
  if (is_default !== undefined) payload.is_default = is_default
  return payload
}
