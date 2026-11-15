'use strict'
const { Menu, app, shell } = require('electron')

function buildMenu({ logsDir, dataDir }) {
  const isMac = process.platform === 'darwin'
  const template = [
    ...(isMac ? [{
      label: app.name,
      submenu: [
        { role: 'about', label: '关于 DongAI' },
        { type: 'separator' },
        { role: 'hide', label: '隐藏 DongAI' },
        { role: 'hideOthers', label: '隐藏其他' },
        { role: 'unhide', label: '全部显示' },
        { type: 'separator' },
        { role: 'quit', label: '退出 DongAI' }
      ]
    }] : []),
    // 编辑菜单必须有：激活页要粘贴授权码，macOS 没有这些 role 时 Cmd+V 不生效
    {
      label: '编辑',
      submenu: [
        { role: 'undo', label: '撤销' },
        { role: 'redo', label: '重做' },
        { type: 'separator' },
        { role: 'cut', label: '剪切' },
        { role: 'copy', label: '复制' },
        { role: 'paste', label: '粘贴' },
        { role: 'selectAll', label: '全选' }
      ]
    },
    {
      label: '窗口',
      submenu: [
        { role: 'minimize', label: '最小化' },
        { role: 'zoom', label: '缩放' },
        ...(isMac ? [] : [{ role: 'quit', label: '退出' }]),
        ...(isMac ? [{ type: 'separator' }, { role: 'front', label: '前置全部窗口' }] : [])
      ]
    },
    {
      label: '帮助',
      submenu: [
        { label: '打开日志文件夹', click: () => shell.openPath(logsDir) },
        { label: '打开数据文件夹', click: () => shell.openPath(dataDir) },
        ...(isMac ? [] : [{ type: 'separator' }, { role: 'about', label: '关于 DongAI' }])
      ]
    }
  ]
  return Menu.buildFromTemplate(template)
}

module.exports = { buildMenu }
