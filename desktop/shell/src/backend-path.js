'use strict'
const os = require('os')
const path = require('path')

/** 把「命令 参数…」切成数组，支持单双引号和反斜杠转义；开头的 ~ 展开为家目录 */
function splitCommand(str, home = os.homedir()) {
  const out = []
  let cur = ''
  let quote = null
  let has = false
  for (let i = 0; i < str.length; i++) {
    const c = str[i]
    if (quote) {
      if (c === quote) quote = null
      else if (c === '\\' && quote === '"' && i + 1 < str.length) cur += str[++i]
      else cur += c
    } else if (c === '"' || c === "'") { quote = c; has = true }
    else if (c === '\\' && i + 1 < str.length) { cur += str[++i]; has = true }
    else if (/\s/.test(c)) { if (cur || has) { out.push(cur); cur = ''; has = false } }
    else { cur += c; has = true }
  }
  if (quote) throw new Error('DONGAI_BACKEND_CMD 引号没有闭合')
  if (cur || has) out.push(cur)
  return out.map(p => (p === '~' ? home : p.startsWith('~/') ? path.join(home, p.slice(2)) : p))
}

/**
 * 解析 sidecar 启动命令。
 * - 打包后：resources/backend/dongai-backend[.exe]；为防环境变量劫持，忽略 DONGAI_BACKEND_CMD，
 *   除非显式 DONGAI_SHELL_ALLOW_DEBUG=1（只给自动化测试用）。
 * - 开发模式：必须设置 DONGAI_BACKEND_CMD。
 */
function resolveBackend({ env, isPackaged, resourcesPath, platform, repoRoot, home }) {
  const allowDebug = env.DONGAI_SHELL_ALLOW_DEBUG === '1'
  const custom = (env.DONGAI_BACKEND_CMD || '').trim()
  if (custom && (!isPackaged || allowDebug)) {
    const parts = splitCommand(custom, home)
    if (!parts.length) throw new Error('DONGAI_BACKEND_CMD 为空')
    const cwd = env.DONGAI_BACKEND_CWD || (!isPackaged && repoRoot ? path.join(repoRoot, 'backend') : undefined)
    return { cmd: parts[0], args: parts.slice(1), cwd, source: 'env' }
  }
  if (!isPackaged) {
    throw new Error('开发模式需要设置环境变量 DONGAI_BACKEND_CMD，例如 "~/.local/dongai-venv/bin/python desktop_entry.py"（在 backend 目录运行）')
  }
  const dir = path.join(resourcesPath, 'backend')
  const exe = path.join(dir, platform === 'win32' ? 'dongai-backend.exe' : 'dongai-backend')
  return { cmd: exe, args: [], cwd: dir, source: 'bundle' }
}

/** 前端目录：打包后在 resources/frontend；开发时用 DONGAI_FRONTEND_DIR 或仓库内 frontend/dist */
function resolveFrontendDir({ env, isPackaged, resourcesPath, repoRoot }) {
  if (isPackaged && env.DONGAI_SHELL_ALLOW_DEBUG !== '1') return path.join(resourcesPath, 'frontend')
  if (env.DONGAI_FRONTEND_DIR) return env.DONGAI_FRONTEND_DIR
  return isPackaged ? path.join(resourcesPath, 'frontend') : path.join(repoRoot, 'frontend', 'dist')
}

/** 传给 sidecar 的环境变量（继承当前环境，覆盖桌面模式必需项，去掉会干扰的项） */
function buildSidecarEnv({ base, dataDir, frontendDir, isPackaged, mongodBin }) {
  const env = { ...base }
  const allowDebug = base.DONGAI_SHELL_ALLOW_DEBUG === '1'
  delete env.DONGAI_LOCAL_TOKEN // 令牌由后端自己生成
  if (isPackaged && !allowDebug) delete env.MONGODB_URL // 打包版一律用随包 mongod
  Object.assign(env, { DONGAI_DESKTOP: '1', DONGAI_DATA_DIR: dataDir, DONGAI_FRONTEND_DIR: frontendDir, PYTHONUNBUFFERED: '1' })
  if (mongodBin) env.DONGAI_MONGOD_BIN = mongodBin
  return env
}

module.exports = { splitCommand, resolveBackend, resolveFrontendDir, buildSidecarEnv }
