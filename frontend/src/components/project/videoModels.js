/** 视频模型（豆包 Seedance 系列）列表：全站只请求一次（风格页选择、分镜页显示共用）。来源 backend/core/video_models.py。 */
import { api } from '@/api'

export const DEFAULT_VIDEO_MODEL = 'seedance-2.0-fast'
let cache = null

export function loadVideoModels() {
  if (!cache) {
    cache = api.config.videoModels()
      .then(res => (res && res.data && res.data.models) || [])
      .catch(e => { cache = null; throw e })
  }
  return cache
}

/** key → 模型；找不到用默认（Fast） */
export function findModel(models, key) {
  return models.find(m => m.key === key) || models.find(m => m.key === DEFAULT_VIDEO_MODEL) || null
}

/** 选项文字：名字 · 说明 · 每段最长秒数 */
export function modelLabel(m) {
  return `${m.name} · ${m.note} · 每段最长 ${m.max_duration} 秒`
}
