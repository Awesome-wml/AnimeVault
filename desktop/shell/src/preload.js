'use strict'
// 单一预加载脚本（sandbox 下只能 require('electron')）：
// - 后端同源页面：注入 window.dongaiDesktop（令牌由主进程按来源校验后经 sendSync 返回，页面脚本运行前就位）；
// - 本地启动画面/错误页（file:）：只暴露 window.shellPage 的两个按钮动作，拿不到令牌。
const { contextBridge, ipcRenderer } = require('electron')

if (location.protocol === 'file:') {
  contextBridge.exposeInMainWorld('shellPage', {
    openLogs: () => ipcRenderer.send('shell:open-logs'),
    retry: () => ipcRenderer.send('shell:retry')
  })
} else {
  const init = ipcRenderer.sendSync('dongai:get-init') || {}
  if (init.localToken) {
    contextBridge.exposeInMainWorld('dongaiDesktop', {
      localToken: init.localToken,
      platform: init.platform,
      version: init.version,
      // 系统没装 Chrome 时回调一次（引导安装的 UI 是 L-07）。已经检测完的结果会立刻补发。
      onChromeMissing(cb) {
        if (typeof cb !== 'function') return () => {}
        const handler = () => cb()
        ipcRenderer.on('dongai:chrome-missing', handler)
        ipcRenderer.invoke('dongai:chrome-status').then(s => { if (s && s.installed === false) cb() }).catch(() => {})
        return () => ipcRenderer.removeListener('dongai:chrome-missing', handler)
      }
    })
  }
}
