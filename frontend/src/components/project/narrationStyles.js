/**
 * 旁白风格（作品上的 narration_style，后端 core/narration.py 的 STYLES 同一套键）。
 * 缺省“剧情动漫”：剧情靠画面和对白推进，旁白只在切入点出现；“小说解说”是另一种内容形态。
 */
export const DEFAULT_NARRATION_STYLE = 'drama'

export const NARRATION_STYLES = [
  { key: 'drama', name: '剧情动漫', note: '旁白只在切入点出现（交代时间地点、时间跳转、内心与态度、收尾），多数段没有旁白' },
  { key: 'half', name: '精简旁白', note: '旁白约占一半，画面已经演出来的不念' },
  { key: 'full', name: '小说解说', note: '原文旁白全念，画面配合旁白' }
]

/** 旁白落在哪个切入点（台词上的 cue 字段） */
export const NARRATION_CUES = { open: '交代时间地点', jump: '时间跳转', mind: '内心与态度', close: '收尾' }

export function narrationStyleOf(project) {
  const key = project && project.narration_style
  return NARRATION_STYLES.some(s => s.key === key) ? key : DEFAULT_NARRATION_STYLE
}
