'use strict'
// 检测系统是否装了 Chrome。只检测与暴露；引导安装的 UI 是 L-07。
const fs = require('fs')
const path = require('path')
const { execFileSync } = require('child_process')

function candidatePaths(platform, env, home) {
  if (platform === 'darwin') {
    return ['/Applications/Google Chrome.app', path.join(home, 'Applications', 'Google Chrome.app')]
  }
  if (platform === 'win32') {
    const roots = [env.PROGRAMFILES, env['PROGRAMFILES(X86)'], env.LOCALAPPDATA].filter(Boolean)
    return roots.map(r => path.join(r, 'Google', 'Chrome', 'Application', 'chrome.exe'))
  }
  return ['/usr/bin/google-chrome', '/usr/bin/google-chrome-stable', '/opt/google/chrome/chrome']
}

function registryChromePath() {
  // Windows 注册表 App Paths（未在 Windows 上实测）
  for (const hive of ['HKLM', 'HKCU']) {
    try {
      const out = execFileSync('reg', ['query', `${hive}\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\App Paths\\chrome.exe`, '/ve'],
        { encoding: 'utf8', timeout: 5000, windowsHide: true })
      const m = out.match(/REG_SZ\s+(.+)/)
      if (m) return m[1].trim()
    } catch (_) { /* 没有 */ }
  }
  return null
}

/** 依赖可注入（exists/registry），便于单测 */
function checkChrome({ platform = process.platform, env = process.env, home = require('os').homedir(), exists = fs.existsSync, registry = registryChromePath } = {}) {
  for (const p of candidatePaths(platform, env, home)) {
    if (exists(p)) return { installed: true, path: p }
  }
  if (platform === 'win32') {
    const p = registry()
    if (p && exists(p)) return { installed: true, path: p }
  }
  return { installed: false, path: null }
}

module.exports = { checkChrome, candidatePaths }
