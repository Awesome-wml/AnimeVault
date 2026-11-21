/** TTS 音色列表：全站只请求一次（角色页、配音页共用）。 */
import { api } from '@/api'

let cache = null

export function loadVoices() {
  if (!cache) {
    cache = api.tts.getVoices()
      .then(res => (res && res.data && res.data.voices) || [])
      .catch(e => { cache = null; throw e })
  }
  return cache
}

/** 下拉里的文字：显示名（年龄段） */
export function voiceOptionLabel(v) {
  return v.age_group ? `${v.display_name}（${v.age_group}）` : v.display_name
}

/** 音色 id → 显示名；找不到时原样返回 */
export function voiceName(voices, id) {
  const v = voices.find(x => x.name === id)
  return v ? v.display_name : (id || '')
}

/** 旁白 / 未绑定音色时后端使用的默认音色（与 backend/api/tts.py 一致） */
export const DEFAULT_VOICE = 'zh_female_qingxin'

/**
 * 音色下拉选项。当前值不在音色列表里（旧数据或已下线的音色）时补一个“未知音色”项，
 * 否则 el-select 会直接显示原始 id。
 */
export function voiceOptions(voices, current) {
  const list = voices.map(v => ({ value: v.name, label: voiceOptionLabel(v) }))
  if (current && voices.length && !voices.some(v => v.name === current)) {
    list.push({ value: current, label: '未知音色（请重新选择）', disabled: true })
  }
  return list
}

/** 声音设定（后端 core/voice_design）的档位与字段 */
export const VOICE_PITCHES = ['低沉', '偏低', '中等', '偏高', '高亮']
export const VOICE_PACES = ['慢', '偏慢', '适中', '偏快', '快']
export const EMPTY_VOICE_DESIGN = { pitch: '', timbre: '', pace: '', manner: '', habit: '' }

/** 角色的声音设定 → 表单草稿（缺的字段补空串） */
export function voiceDesignDraft(item) {
  return { ...EMPTY_VOICE_DESIGN, ...((item && item.voice_design) || {}) }
}

/** 声音设定来源的说明文字 */
export function voiceSourceText(source) {
  return { ai: 'AI 设计', rule: '按年龄气质推的基础设定', user: '手动设定' }[source] || ''
}
