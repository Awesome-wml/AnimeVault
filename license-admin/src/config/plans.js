/**
 * 套餐白名单和功能点候选的「兜底值」。
 * 正常情况下管理端登录后会从服务端 GET /admin/api/meta 取（套餐来自 LS_PLANS，功能点规则和候选来自服务端），
 * 取不到时才回退到这里的常量；部署时可用 VUE_APP_PLANS=trial,basic,pro 覆盖兜底套餐。
 */
import { buildPlanOptions, PLAN_LABELS } from '@/utils/meta'

const fromEnv = (process.env.VUE_APP_PLANS || '').split(',').map(s => s.trim()).filter(Boolean)
export const PLAN_VALUES = fromEnv.length ? fromEnv : ['trial', 'basic', 'pro', 'enterprise']
export const PLANS = buildPlanOptions(PLAN_VALUES)

/** 常用功能点（服务端只校验格式：小写字母、数字、下划线，最长 40）。可手动输入新的功能点。 */
export const FEATURE_OPTIONS = ['video', 'image', 'novel', 'voice', 'export_hd']

export const FEATURE_PATTERN = /^[a-z0-9_]{1,40}$/

export const META_FALLBACK = {
  plans: PLAN_VALUES, features: FEATURE_OPTIONS, pattern: FEATURE_PATTERN, devMax: { min: 1, max: 100 }
}

export function planLabel(value) {
  return PLAN_LABELS[value] || value || '-'
}
