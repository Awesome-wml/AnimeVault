/** 拆分镜是“覆盖重拆”：后端会删掉本集全部旧镜头（含已出的视频、画面、配音引用）再重新编号。
 *  拆之前先查本集现有镜头，有镜头时明确告诉用户会删掉多少、其中多少已出视频。 */
import { api } from '@/api'
import { confirmAction } from '@/utils/dialogs'
import { resplitMessage } from './resplitText'

export { resplitMessage }

/** 返回 true 表示可以继续拆分（本集没有镜头，或用户确认覆盖） */
export async function confirmResplit(projectId, episodeId, where) {
  let shots = []
  try {
    const list = await api.shot.list(projectId, episodeId)
    shots = Array.isArray(list) ? list : []
  } catch (e) {
    // 查不到就按“有镜头”的保守口径提示
    return confirmAction(`重新拆分镜会删除${where || '当前剧集'}现有的全部镜头（含已出视频），此操作不能撤销。`, '覆盖重拆', '删除并重拆')
  }
  if (!shots.length) return true
  return confirmAction(resplitMessage(shots, where), '覆盖重拆', '删除并重拆')
}
