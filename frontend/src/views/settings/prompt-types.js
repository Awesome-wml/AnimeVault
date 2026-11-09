/**
 * 提示词类型（与后端 prompt.type、core/builtin_prompts.BUILTIN_TYPES 对应）。
 * short 用于筛选按钮和表格，label 用于下拉。
 * 旧的 video（视频提示词）已废弃：视频提示词由系统按分镜组装，不走提示词表（见 VIDEO_PROMPT_NOTE）。
 */
export const PROMPT_TYPES = [
  { value: 'novel', short: '小说', label: '生成小说' },
  { value: 'novel_polish', short: '润色', label: '小说润色' },
  { value: 'script_convert', short: '剧本', label: '剧本转换' },
  { value: 'character_extract', short: '角色', label: '角色提取' },
  { value: 'prop_extract', short: '道具', label: '道具提取' },
  { value: 'scene_extract', short: '场景', label: '场景提取' },
  { value: 'asset_extract', short: '资产三合一', label: '资产提取（三合一）' },
  { value: 'character_sheet', short: '三视图', label: '角色三视图' },
  { value: 'prop_ref', short: '道具图', label: '道具参考图' },
  { value: 'scene_ref', short: '场景图', label: '场景参考图' },
  { value: 'split_shots', short: '拆分镜', label: '拆分镜（小说）' },
  { value: 'split_shots_script', short: '拆分镜·剧本', label: '拆分镜（剧本）' },
  { value: 'prompt_optimize', short: '提示词优化', label: '文生图提示词优化' }
]

/** 页面上对“视频提示词”类型的说明 */
export const VIDEO_PROMPT_NOTE = '视频提示词由系统按每段分镜的角色、场景、台词自动组装，不在这里配置。'

export function promptTypeShort(value) {
  const t = PROMPT_TYPES.find(x => x.value === value)
  return t ? t.short : (value || '')
}

export function promptTypeLabel(value) {
  const t = PROMPT_TYPES.find(x => x.value === value)
  return t ? t.label : (value || '')
}
