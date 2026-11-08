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

/** 模型预设 → 分组选项 + 默认值 */
export async function loadModelOptions() {
  const res = await api.model.list()
  const list = (res && res.data) || []
  const map = {}
  list.forEach(m => {
    const p = m.provider || 'other'
    const items = modelsOf(m).map(mid => ({ key: `${m._id}::${mid}`, label: `${m.name}（${mid}）` }))
    ;(map[p] = map[p] || []).push(...items)
  })
  const providers = [...PROVIDER_ORDER.filter(p => map[p]), ...Object.keys(map).filter(p => !PROVIDER_ORDER.includes(p))]
  const groups = providers.map(p => ({ provider: p, label: PROVIDER_LABELS[p] || p, items: map[p] }))
  const def = list.find(m => m.is_default) || list[0]
  const defaultKey = def && modelsOf(def)[0] ? `${def._id}::${modelsOf(def)[0]}` : ''
  return { groups, defaultKey }
}

export function parseModelKey(key) {
  const [id, ...rest] = (key || '').split('::')
  return { model_id: id || '', model: rest.join('::') || '' }
}

/** 全部提示词，按类型分好；只保留“通用”和本作品题材的 */
export async function loadPrompts(genre) {
  const res = await api.prompt.list('')
  const all = (res && res.data) || []
  const match = p => {
    const c = p.category || '通用'
    return c === '通用' || !genre || c === genre
  }
  const byType = type => all.filter(p => p.type === type && match(p))
  return {
    extract: byType('asset_extract'),
    split: byType('split_shots'),
    novel: byType('novel'),
    polish: byType('novel_polish')
  }
}

/** 润色人称（后端 person 参数） */
export const PERSON_OPTIONS = [
  { value: '', label: '保持原样' },
  { value: 'first', label: '第一人称' },
  { value: 'third', label: '第三人称' }
]
