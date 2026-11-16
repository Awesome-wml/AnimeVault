'use strict'
const { shell } = require('electron')

// 前端现状（已核对 frontend/dist）：脚本、样式、字体、图片、媒体都是同源；index.html 有一段 inline <style>，
// Element UI / Vue 运行时会写 style 属性，所以 style-src 需要 'unsafe-inline'；图片/视频预览用到 blob: 和 data:；
// app.js 里有 new Function（第三方库的模板编译），所以 script-src 需要 'unsafe-eval'。其余一律只允许本应用同源。
function buildCsp(origin) {
  return [
    `default-src 'self'`,
    `script-src 'self' 'unsafe-eval'`,
    `style-src 'self' 'unsafe-inline'`,
    `img-src 'self' data: blob:`,
    `media-src 'self' blob: data:`,
    `font-src 'self' data:`,
    `connect-src 'self'`,
    `worker-src 'self' blob:`,
    `object-src 'none'`,
    `base-uri 'self'`,
    `form-action 'self'`,
    `frame-ancestors 'none'`
  ].join('; ')
}

function isHttpUrl(u) {
  try { const p = new URL(u).protocol; return p === 'http:' || p === 'https:' } catch (_) { return false }
}

function openExternalSafe(u) {
  if (isHttpUrl(u)) shell.openExternal(u)
}

/**
 * 给会话装安全策略：CSP 响应头、拒绝所有权限（只放行剪贴板写入，激活页的「复制机器码」要用）。
 * getOrigin() 返回当前后端同源地址（可能为空）。
 */
function installSessionSecurity(session, getOrigin) {
  session.webRequest.onHeadersReceived((details, cb) => {
    const origin = getOrigin()
    const headers = { ...details.responseHeaders }
    if (origin && details.url.startsWith(origin + '/') && details.resourceType !== 'xhr' && details.resourceType !== 'fetch') {
      for (const k of Object.keys(headers)) if (k.toLowerCase() === 'content-security-policy') delete headers[k]
      headers['Content-Security-Policy'] = [buildCsp(origin)]
    }
    cb({ responseHeaders: headers })
  })
  session.setPermissionRequestHandler((wc, permission, cb) => cb(permission === 'clipboard-sanitized-write'))
  session.setPermissionCheckHandler((wc, permission) => permission === 'clipboard-sanitized-write')
}

/** 导航限制：只允许本应用源和本地页面；其余拦截，http/https 交给系统浏览器 */
function guardWebContents(contents, { isAllowedUrl }) {
  contents.setWindowOpenHandler(({ url }) => {
    openExternalSafe(url)
    return { action: 'deny' }
  })
  contents.on('will-navigate', (event, url) => {
    if (isAllowedUrl(url)) return
    event.preventDefault()
    openExternalSafe(url)
  })
  contents.on('will-redirect', (event, url) => {
    if (!isAllowedUrl(url)) event.preventDefault()
  })
  contents.on('will-attach-webview', event => event.preventDefault())
}

module.exports = { buildCsp, installSessionSecurity, guardWebContents, isHttpUrl, openExternalSafe }
