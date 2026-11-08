/** 提示词类型（与后端 prompt.type 对应）。short 用于筛选按钮和表格，label 用于下拉。 */
export const PROMPT_TYPES = [
  { value: 'video', short: '视频', label: '视频提示词' },
  { value: 'split_shots', short: '拆分镜', label: '拆分镜' },
  { value: 'novel', short: '小说', label: '生成小说' },
  { value: 'character_extract', short: '角色', label: '角色提取' },
  { value: 'prop_extract', short: '道具', label: '道具提取' },
  { value: 'scene_extract', short: '场景', label: '场景提取' },
  { value: 'asset_extract', short: '资产三合一', label: '资产提取（三合一）' },
  { value: 'character_sheet', short: '三视图', label: '角色三视图' },
  { value: 'prompt_optimize', short: '提示词优化', label: '提示词优化' }
]

export function promptTypeShort(value) {
  const t = PROMPT_TYPES.find(x => x.value === value)
  return t ? t.short : (value || '')
}
