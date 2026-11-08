/** 剧本场次的小工具（剧本页、场次卡片、编辑器共用）。 */

export const NARRATOR = '旁白'

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
    dialogues: (scene.dialogues || []).map(d => ({ speaker: d.speaker || NARRATOR, line: d.line || '' }))
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
      .map(d => ({ speaker: String(d.speaker || '').trim() || NARRATOR, line: String(d.line || '').trim() }))
      .filter(d => d.line)
  }
}
