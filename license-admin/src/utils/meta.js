/** /meta 接口的结果整理。纯函数：服务端数据不合法时逐项回退，保证页面永远拿到可用的配置。 */
export const PLAN_LABELS = { trial: '试用', basic: '基础', pro: '专业', enterprise: '企业' }

export function buildPlanOptions(values) {
  return values.map(value => ({ value, label: PLAN_LABELS[value] || value }))
}

const isStrList = v => Array.isArray(v) && v.length > 0 && v.every(x => typeof x === 'string' && x.trim())

function toRegExp(src) {
  if (typeof src !== 'string' || src.length > 200 || !src.startsWith('^') || !src.endsWith('$')) return null
  try { return new RegExp(src) } catch (e) { return null }
}

function toRange(r, fb) {
  const ok = r && Number.isInteger(r.min) && Number.isInteger(r.max) && r.min >= 1 && r.max >= r.min
  return ok ? { min: r.min, max: r.max } : fb
}

/**
 * @param {object|null} meta  GET /admin/api/meta 的返回，可能为空（请求失败）
 * @param {{plans:string[], features:string[], pattern:RegExp, devMax:{min:number,max:number}}} fallback
 */
export function normalizeMeta(meta, fallback) {
  const m = meta && typeof meta === 'object' ? meta : {}
  const f = m.features && typeof m.features === 'object' ? m.features : {}
  const planValues = isStrList(m.plans) ? m.plans.map(s => s.trim()) : fallback.plans
  const pattern = toRegExp(f.pattern) || fallback.pattern
  const candidates = isStrList(f.candidates) ? f.candidates.filter(x => pattern.test(x)) : []
  return {
    plans: buildPlanOptions(planValues),
    featureOptions: candidates.length ? candidates : fallback.features,
    featurePattern: pattern,
    devMax: toRange(m.dev_max, fallback.devMax),
    fromServer: isStrList(m.plans)
  }
}
