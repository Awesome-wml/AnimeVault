/**
 * 小说页用到的下拉数据：模型预设、提示词。每次进页面各请求一次，几个下拉共用。
 * 模型选项的值是 "记录id::模型名"，提交时用 parseModelKey 拆成 { model_id, model }。
 */
import { api } from '@/api'

import { buildModelOptions } from './modelGroups'

/** 模型预设 → 按用途分开的下拉选项 + 默认值，见 modelGroups.js。
 *  返回 { chatGroups, imageGroups, chatDefaultKey, imageDefaultLabel }：
 *  文字环节的下拉用 chatGroups，出图设置用 imageGroups，两边互不出现对方的模型。 */
export async function loadModelOptions() {
  const res = await api.model.list()
  return buildModelOptions((res && res.data) || [])
}

/** 选中模型的长输出提示（如“建议拆分镜用 …”）；没有返回空串 */
export function modelAdvice(groups, key) {
  for (const g of groups || []) {
    const item = (g.items || []).find(i => i.key === key)
    if (item) return item.advice || ''
  }
  return ''
}

export function parseModelKey(key) {
  const [id, ...rest] = (key || '').split('::')
  return { model_id: id || '', model: rest.join('::') || '' }
}

/** 业务页下拉分组 → 后端注册表环节 key（/api/prompts 的 row.type）；一个分组可合并多个环节 */
const PROMPT_GROUPS = {
  polish: ['novel_polish'],
  novel: ['novel'],
  script: ['script_convert'],
  extract: ['asset_extract'],
  split: ['split_shots', 'split_shots_script'],
  sheet: ['character_sheet']
}

const EMPTY_PROMPTS = { extract: [], split: [], novel: [], polish: [], script: [], sheet: [] }

/**
 * 从后端注册表（core/prompts/*.json）拉取只读提示词，按业务环节分组。
 * 每个环节含通用条目和题材变体条目；不选即用后端默认。
 */
export async function loadPrompts() {
  try {
    const res = await api.prompt.list()
    const rows = (res && res.data) || []
    const byType = {}
    rows.forEach(r => { (byType[r.type] = byType[r.type] || []).push(r) })
    const out = { ...EMPTY_PROMPTS }
    Object.keys(PROMPT_GROUPS).forEach(group => {
      out[group] = PROMPT_GROUPS[group].flatMap(k => byType[k] || [])
    })
    return out
  } catch (e) {
    return { ...EMPTY_PROMPTS }
  }
}

/** 润色人称（后端 person 参数） */
export const PERSON_OPTIONS = [
  { value: '', label: '保持原样' },
  { value: 'first', label: '第一人称' },
  { value: 'third', label: '第三人称' }
]
