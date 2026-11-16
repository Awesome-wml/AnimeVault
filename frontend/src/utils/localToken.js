/**
 * 桌面模式本地令牌（对应后端 core/local_token.py）。
 * 桌面外壳（Electron/Tauri 的 preload）在页面脚本运行前注入下面两者之一：
 *   window.__DONGAI_LOCAL_TOKEN__ = '<与后端 DONGAI_LOCAL_TOKEN 相同的值>'
 *   window.dongaiDesktop = { localToken: '<同上>' }
 * 有值就给每个请求加请求头 X-DongAI-Local-Token，没有就不加（开发环境、浏览器访问不受影响）。
 */
export const LOCAL_TOKEN_HEADER = 'X-DongAI-Local-Token'

export function getLocalToken(win = typeof window !== 'undefined' ? window : undefined) {
  if (!win) return ''
  const t = win.__DONGAI_LOCAL_TOKEN__ || (win.dongaiDesktop && win.dongaiDesktop.localToken)
  return typeof t === 'string' ? t.trim() : ''
}

/** 需要追加的请求头（没有令牌时为空对象），axios 与 fetch 共用 */
export function localTokenHeaders(win) {
  const t = getLocalToken(win)
  return t ? { [LOCAL_TOKEN_HEADER]: t } : {}
}
