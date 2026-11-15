'use strict'
// 自动更新占位。L-65 会在这里接入 electron-updater（检查更新、下载、签名校验、安装重启）。
// 现在是空实现：不联网、不检查更新。保留这个模块是为了让 main.js 的调用点和打包配置（publish）不用改结构。
function initUpdater(/* { app, getWindow, log } */) {
  return { checkNow: async () => ({ supported: false }) }
}

module.exports = { initUpdater }
