'use strict'
const fs = require('fs')
const path = require('path')

const DEFAULTS = { width: 1440, height: 900 }
const MIN = { width: 1100, height: 700 }

function sanitize(raw) {
  if (!raw || typeof raw !== 'object') return null
  const int = v => (Number.isFinite(v) ? Math.round(v) : null)
  const width = int(raw.width)
  const height = int(raw.height)
  if (width === null || height === null || width < MIN.width || height < MIN.height || width > 10000 || height > 10000) return null
  const out = { width, height, maximized: raw.maximized === true }
  const x = int(raw.x)
  const y = int(raw.y)
  if (x !== null && y !== null) { out.x = x; out.y = y }
  return out
}

/** 读状态；文件不存在、损坏、数值非法都回退默认 */
function loadWindowState(file) {
  try {
    const s = sanitize(JSON.parse(fs.readFileSync(file, 'utf8')))
    if (s) return s
  } catch (_) { /* 回退默认 */ }
  return { ...DEFAULTS, maximized: false }
}

function saveWindowState(file, state) {
  const s = sanitize(state)
  if (!s) return false
  try {
    fs.mkdirSync(path.dirname(file), { recursive: true })
    fs.writeFileSync(file, JSON.stringify(s))
    return true
  } catch (_) { return false }
}

/** 位置必须落在某个显示器内（至少 100x50 可见），否则丢弃 x/y 让系统居中；displays 为 [{x,y,width,height}] */
function fitToDisplays(state, displays) {
  if (state.x === undefined || state.y === undefined) return state
  const visible = displays.some(d => {
    const w = Math.min(state.x + state.width, d.x + d.width) - Math.max(state.x, d.x)
    const h = Math.min(state.y + state.height, d.y + d.height) - Math.max(state.y, d.y)
    return w >= 100 && h >= 50
  })
  if (visible) return state
  const { x, y, ...rest } = state
  return rest
}

module.exports = { loadWindowState, saveWindowState, fitToDisplays, DEFAULTS, MIN }
