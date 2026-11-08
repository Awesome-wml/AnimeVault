/**
 * 统一的操作反馈（轻提示）。页面里不直接拼 this.$message，也不写空 catch：
 *   try { ... } catch (e) { toastError(e, '生成失败') }
 * 或直接用 runAction 包住一次操作。
 *
 * 请求失败时 api/index.js 的拦截器已经弹过后端原因，并给 error 打上 notified 标记，
 * 这里不会重复弹；其它异常（代码错误、SSE 断开等）才显示 fallback 文案。
 */
import { Message } from 'element-ui'

export function toastSuccess(message) {
  if (message) Message.success(message)
}

export function toastInfo(message) {
  if (message) Message.info(message)
}

export function toastWarning(message) {
  if (message) Message.warning(message)
}

export function toastError(error, fallback = '操作失败') {
  if (error && error.notified) return
  const reason = error && error.message ? `：${error.message}` : ''
  Message.error(`${fallback}${reason}`)
  // 保留原始异常便于排查
  console.error(fallback, error)
}

/**
 * 执行一次操作并给出反馈。成功返回 fn 的结果；失败已提示，返回 undefined。
 * @param {() => Promise<any>} fn
 * @param {{ success?: string | ((res:any) => string), error?: string }} [opts]
 */
export async function runAction(fn, opts = {}) {
  try {
    const res = await fn()
    const msg = typeof opts.success === 'function' ? opts.success(res) : opts.success
    toastSuccess(msg)
    return res === undefined ? true : res
  } catch (e) {
    toastError(e, opts.error)
    return undefined
  }
}
