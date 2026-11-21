/** 视频模型（豆包 Seedance 系列）列表：全站只请求一次（风格页选择、分镜页显示共用）。来源 backend/core/video_models.py。
 *  同一接口还带 pacing（语速/余量口径，来源 backend/core/pacing.py），剧本页“目标时长 → 台词字数”提示用它，前端不另写常数。 */
import { api } from '@/api'

export const DEFAULT_VIDEO_MODEL = 'seedance-2.0-fast'
let cache = null

function loadConfig() {
  if (!cache) {
    cache = api.config.videoModels()
      .then(res => (res && res.data) || {})
      .catch(e => { cache = null; throw e })
  }
  return cache
}

export function loadVideoModels() {
  return loadConfig().then(data => data.models || [])
}

/** 语速口径 { chars_per_second, speech_margin_seconds, first_frame_hold_seconds, measured }；接口没带时为 null */
export function loadPacing() {
  return loadConfig().then(data => data.pacing || null)
}

/** key → 模型；找不到用默认（Fast） */
export function findModel(models, key) {
  return models.find(m => m.key === key) || models.find(m => m.key === DEFAULT_VIDEO_MODEL) || null
}

/** 选项文字：名字 · 说明 · 每段最长秒数 */
export function modelLabel(m) {
  return `${m.name} · ${m.note} · 每段最长 ${m.max_duration} 秒`
}
