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
