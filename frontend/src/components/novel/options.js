/**
 * 小说页用到的下拉数据：模型预设、提示词。每次进页面各请求一次，几个下拉共用。
 * 模型选项的值是 "记录id::模型名"，提交时用 parseModelKey 拆成 { model_id, model }。
 */
import { api } from '@/api'

const PROVIDER_LABELS = { zhipu: '智谱 GLM', deepseek: 'DeepSeek', openai: 'OpenAI', gemini: 'Google Gemini', other: '其他' }
const PROVIDER_ORDER = ['zhipu', 'deepseek', 'openai', 'gemini', 'other']

function modelsOf(m) {
  return m.models || (m.model ? [m.model] : [])
}

/** 模型预设 → 分组选项 + 默认值；列出全部模型，不再按对话/文生图过滤。
 *  分组标题用预设名（如“智谱-image”“Google Gemini”），组内选项是这条预设配置的各个模型 ID。 */
export async function loadModelOptions() {
  const res = await api.model.list()
  const list = ((res && res.data) || [])
  const groups = list.map(m => {
    // advice：后端 model_caps.LONG_OUTPUT_ADVICE 判定的“拆分镜等长输出不稳”提示（页面只显示，不写死模型名）
    const advice = m.long_output_advice || {}
    return {
      provider: m.provider || 'other',
      label: m.name || PROVIDER_LABELS[m.provider] || m.provider || '未命名预设',
      items: modelsOf(m).map(mid => ({
        key: `${m._id}::${mid}`,
        label: mid,
        advice: (advice[mid] && advice[mid].message) || ''
      }))
    }
  })
  const keyOf = m => (m && modelsOf(m)[0]) ? `${m._id}::${modelsOf(m)[0]}` : ''
  // 对话类环节（转剧本/提取/拆分镜）默认选中非文生图预设；出图环节另取文生图预设
  const defChat = list.find(m => m.is_default && m.model_type !== 'image') || list.find(m => m.model_type !== 'image')
  const defImage = list.find(m => m.is_default && m.model_type === 'image') || list.find(m => m.model_type === 'image')
  return {
    groups,
    defaultKey: keyOf(defChat || defImage),
    chatDefaultKey: keyOf(defChat),
    imageDefaultKey: keyOf(defImage)
  }
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
