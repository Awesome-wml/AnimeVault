'use strict'
// 自动更新占位。静默热更新（electron-updater）依赖已签名发布与更新源，当前不做；现行方案是应用内下载 + 校验 sha256 +
// 用户手动安装（update-download.js / main.js 的 dongai:update-download）。升级条件见 docs/versioning.md「升级到 electron-updater」。
// 现在是空实现：不联网、不检查更新。保留这个模块是为了让 main.js 的调用点和打包配置（publish）不用改结构。
function initUpdater(/* { app, getWindow, log } */) {
  return { checkNow: async () => ({ supported: false }) }
}

module.exports = { initUpdater }
