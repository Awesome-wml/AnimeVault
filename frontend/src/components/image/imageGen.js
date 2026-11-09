/**
 * 出图设置（资产参考图 / 分镜画面共用）：文生图模型预设 + 子模型、角色三视图提示词。
 * 按作品记在浏览器本地（只是个人偏好，读写失败就用默认）。
 *   const s = readImageGen(pid)           // { model: '记录id::子模型' | '', sheetPrompt: '' }
 *   api.asset.generate({ ..., ...imageGenPayload(s, isCharacter) })
 */
import { parseModelKey } from '@/components/novel/options'

const KEY = pid => `dongai:imageGen:${pid}`

export function readImageGen(pid) {
  try {
    const v = JSON.parse(localStorage.getItem(KEY(pid)) || '{}')
    return { model: v.model || '', sheetPrompt: v.sheetPrompt || '' }
  } catch (e) {
    return { model: '', sheetPrompt: '' }
  }
}

export function saveImageGen(pid, settings) {
  try { localStorage.setItem(KEY(pid), JSON.stringify(settings)) } catch (e) { /* 隐私模式 */ }
}

/** 请求参数：没选模型时不传，后端用账号默认文生图模型；三视图提示词只对角色生效 */
export function imageGenPayload(settings, withSheetPrompt = false) {
  const out = {}
  if (settings && settings.model) Object.assign(out, parseModelKey(settings.model))
  if (withSheetPrompt && settings && settings.sheetPrompt) out.prompt_id = settings.sheetPrompt
  return out
}

/** 下拉里选中项的文字（副标题显示“出图：xxx”），找不到返回空 */
export function modelLabel(groups, key) {
  for (const g of groups || []) {
    const hit = (g.items || []).find(i => i.key === key)
    if (hit) return hit.label
  }
  return ''
}
