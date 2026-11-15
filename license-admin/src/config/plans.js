/**
 * 套餐白名单。必须与授权服务环境变量 LS_PLANS 保持一致（默认 trial,basic,pro,enterprise）。
 * 服务端目前没有接口暴露套餐列表，所以这里先做成常量；
 * 部署时可用 VUE_APP_PLANS=trial,basic,pro 在构建时覆盖。
 */
const LABELS = { trial: '试用', basic: '基础', pro: '专业', enterprise: '企业' }

const fromEnv = (process.env.VUE_APP_PLANS || '').split(',').map(s => s.trim()).filter(Boolean)
export const PLANS = (fromEnv.length ? fromEnv : ['trial', 'basic', 'pro', 'enterprise'])
  .map(value => ({ value, label: LABELS[value] || value }))

/** 常用功能点（服务端只校验格式：小写字母、数字、下划线，最长 40）。可手动输入新的功能点。 */
export const FEATURE_OPTIONS = ['video', 'image', 'novel', 'voice', 'export_hd']

export const FEATURE_PATTERN = /^[a-z0-9_]{1,40}$/

export function planLabel(value) {
  const p = PLANS.find(x => x.value === value)
  return p ? p.label : value || '-'
}
