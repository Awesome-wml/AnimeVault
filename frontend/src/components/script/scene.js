/** 剧本场次的小工具（剧本页、场次卡片、编辑器共用）。 */

export const NARRATOR = '旁白'

/** 转剧本旁白人称（后端 person / project.script_person），默认沿用原文 */
export const DEFAULT_SCRIPT_PERSON = 'keep'
export const SCRIPT_PERSON_OPTIONS = [
  { value: 'keep', label: '沿用原文' },
  { value: 'first', label: '第一人称（主角“我”）' },
  { value: 'third', label: '第三人称' }
]

/** 台词类型（后端 dialogues[].kind）：顺序即下拉顺序 */
export const LINE_KINDS = [
  { value: 'onscreen', label: '当面', hint: '说话人在画面里开口' },
  { value: 'inner', label: '心声', hint: '角色心里的话，画面里不开口' },
  { value: 'offscreen', label: '画外', hint: '说话人不在画面里（电话、门外）' },
  { value: 'narration', label: '旁白', hint: '旁白讲述' }
]

/** kind 兜底，与后端 core/script_text.normalize_kind 一致：旁白一律 narration；缺省按说话人推断 */
export function lineKind(d) {
  const speaker = String((d && d.speaker) || '').trim() || NARRATOR
  const kind = String((d && d.kind) || '').trim().toLowerCase()
  if (speaker === NARRATOR || kind === 'narration') return 'narration'
  return LINE_KINDS.some(k => k.value === kind) ? kind : 'onscreen'
}

export function kindLabel(kind) {
  const k = LINE_KINDS.find(x => x.value === kind)
  return k ? k.label : ''
}

/** 场次标题：第 N 场 · 地点 · 时间 */
export function sceneTitle(scene) {
  const parts = [`第 ${scene.scene_no} 场`]
  if (scene.location) parts.push(scene.location)
  if (scene.time) parts.push(scene.time)
  return parts.join(' · ')
}

/** 编辑草稿：深拷贝可编辑字段，取消时直接丢弃 */
export function sceneDraft(scene) {
  return {
    location: scene.location || '',
    time: scene.time || '',
    characters: (scene.characters || []).slice(),
    action: scene.action || '',
    beat: scene.beat || '',
    summary: scene.summary || '',
    dialogues: (scene.dialogues || []).map(d => ({ speaker: d.speaker || NARRATOR, line: d.line || '', kind: lineKind(d) }))
  }
}

/** 保存前整理：去空白、丢掉空台词（后端也会丢，这里先丢让界面立即一致） */
export function cleanDraft(draft) {
  return {
    ...draft,
    location: draft.location.trim(),
    time: draft.time.trim(),
    characters: draft.characters.map(c => String(c).trim()).filter(Boolean),
    dialogues: draft.dialogues
      .map(d => {
        const speaker = String(d.speaker || '').trim() || NARRATOR
        const kind = lineKind({ speaker, kind: d.kind })
        return { speaker: kind === 'narration' ? NARRATOR : speaker, line: String(d.line || '').trim(), kind }
      })
      .filter(d => d.line)
  }
}
