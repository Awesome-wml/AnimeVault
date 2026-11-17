'use strict'
// 构建前检查：仓库根 VERSION 与 desktop/shell/package.json 的版本必须一致，否则构建失败。
// 不一致时在仓库根运行 `python3 desktop/sync_version.py`（会从 VERSION 同步）。
const fs = require('fs')
const path = require('path')

function readVersionFile(file) {
  const text = fs.readFileSync(file, 'utf8').trim()
  return text.split(/\r?\n/)[0].trim()
}

function checkVersions(versionFile, pkgFile) {
  const v = readVersionFile(versionFile)
  const p = JSON.parse(fs.readFileSync(pkgFile, 'utf8')).version
  if (!/^\d+\.\d+\.\d+(-[0-9A-Za-z.-]+)?$/.test(v)) return { ok: false, message: `VERSION 不合法：${v}` }
  if (v !== p) return { ok: false, message: `版本不一致：VERSION=${v}，desktop/shell/package.json=${p}。先运行 python3 desktop/sync_version.py` }
  return { ok: true, version: v }
}

module.exports = { checkVersions, readVersionFile }

if (require.main === module) {
  const r = checkVersions(path.resolve(__dirname, '..', '..', '..', 'VERSION'), path.resolve(__dirname, '..', 'package.json'))
  if (!r.ok) {
    console.error(r.message)
    process.exit(1)
  }
  console.log(`版本一致：${r.version}`)
}
