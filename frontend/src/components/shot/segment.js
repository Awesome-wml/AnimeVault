/**
 * 视频段（一条 = 一次视频生成）的展示口径：逐句台词类型、时间格式、段与旧数据（一镜一声）的区分。
 * 字段由后端 /api/shots 返回：lines [{ speaker, text, kind, start, end }]、beats、duration、fill_rate、speech_seconds。
 */
import { NARRATOR } from './status'

export const LINE_KINDS = [
  { value: 'onscreen', label: '对白' },
  { value: 'narration', label: '旁白' },
  { value: 'inner', label: '心声' },
  { value: 'offscreen', label: '画外音' }
]
const KIND_LABEL = Object.fromEntries(LINE_KINDS.map(k => [k.value, k.label]))

export function kindLabel(kind) {
  return KIND_LABEL[kind] || '旁白'
}

/** 有逐句台词的是视频段；旧数据没有 lines，照旧按一镜一声显示 */
export function isSegment(shot) {
  return !!(shot && Array.isArray(shot.lines) && shot.lines.length)
}

/** 秒数显示：整数不带小数，其余保留一位 */
export function sec(v) {
  const n = Math.round((Number(v) || 0) * 10) / 10
  return Number.isInteger(n) ? String(n) : n.toFixed(1)
}

export function timeRange(item) {
  return `${sec(item.start)}–${sec(item.end)} 秒`
}

/** 镜头/段的称呼：视频段叫“第 N 段”，旧数据叫“镜头 N” */
export function shotTitle(shot) {
  return isSegment(shot) ? `第 ${shot.shot_no} 段` : `镜头 ${shot.shot_no}`
}

/** 一句台词的说话人显示：旁白直接显示“旁白”，其余“名字 · 类型” */
export function lineSpeaker(line) {
  if (!line || line.kind === 'narration' || line.speaker === NARRATOR) return NARRATOR
  return `${line.speaker} · ${kindLabel(line.kind)}`
}

/** 拆分镜结果提示：视频段说“N 段”，旧格式说“N 个镜头” */
export function splitMessage(res) {
  const d = (res && res.data) || {}
  const n = d.count || 0
  return d.format === 'legacy' ? `拆分镜完成：${n} 个镜头` : `拆分镜完成：${n} 段，每段一次视频生成`
}
