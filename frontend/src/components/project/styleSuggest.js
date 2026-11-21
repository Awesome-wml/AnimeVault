/**
 * 风格 AI 识别（backend/core/style_suggest.py）：新建作品不用手选画面类型和题材，
 * 作品标记 style_source=auto，贴入小说保存后自动识别；用户在风格页保存过（style_source=user）就不再自动覆盖。
 */
import { api } from '@/api'

export const STYLE_AUTO = 'auto'
export const STYLE_AI = 'ai'
export const MIN_STYLE_TEXT = 200   // 与后端 MIN_TEXT_CHARS 一致：正文太短识别不准

export function suggestionLabel(s) {
  return s ? `${s.medium_name} · ${s.genre_name}` : ''
}

export function needsAutoStyle(project) {
  return !!project && project.style_source === STYLE_AUTO
}

/** 待识别的作品：按本集正文识别并写回，返回识别结果（失败或不需要时返回 null，不抛异常） */
export async function autoDetectStyle(store, project, episodeId, text) {
  if (!needsAutoStyle(project) || (text || '').trim().length < MIN_STYLE_TEXT) return null
  try {
    const res = await api.project.suggestStyle(project.id, { video_set_id: episodeId || '', apply: true })
    const s = res && res.data
    if (!s) return null
    store.commit('project/SET_PROJECT', {
      ...project, medium: s.medium, genre: s.genre, style: '', style_source: STYLE_AI, style_reason: s.style_reason
    })
    return s
  } catch (e) {
    return null
  }
}
