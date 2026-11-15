/** 时间工具。后端时间字段都是 Unix 秒。 */
const pad = n => String(n).padStart(2, '0')

export function formatTime(sec, withTime = true) {
  if (!sec) return '-'
  const d = new Date(sec * 1000)
  const date = `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
  return withTime ? `${date} ${pad(d.getHours())}:${pad(d.getMinutes())}` : date
}

export function startOfToday(now = new Date()) {
  return new Date(now.getFullYear(), now.getMonth(), now.getDate())
}

/** 日期选择的结果 -> 当天 23:59:59（本地时区）的 Unix 秒。 */
export function endOfDaySeconds(date) {
  const d = new Date(date.getFullYear(), date.getMonth(), date.getDate(), 23, 59, 59)
  return Math.floor(d.getTime() / 1000)
}

/** el-date-picker 的 disabledDate：不能早于今天。 */
export function isBeforeToday(date, now = new Date()) {
  return date.getTime() < startOfToday(now).getTime()
}
