/** 复制文本到剪贴板：优先 Clipboard API，不可用（非安全上下文等）时退回 execCommand。成功返回 true。 */
export async function copyText(text) {
  try {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(text)
      return true
    }
  } catch (_) { /* 退回旧方式 */ }
  const el = document.createElement('textarea')
  el.value = text
  el.setAttribute('readonly', '')
  el.style.position = 'fixed'
  el.style.opacity = '0'
  document.body.appendChild(el)
  el.select()
  let ok = false
  try { ok = document.execCommand('copy') } catch (_) { ok = false }
  document.body.removeChild(el)
  return ok
}
