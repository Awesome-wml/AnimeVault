/** 导出类操作（成片页、配音页、管理剧集页共用），自带成功/失败提示。 */
import { api } from '@/api'
import { runAction } from '@/utils/notify'

/** 写剪映草稿并打开剪映。后端失败时 HTTP 仍是 200，ok=false 带原因。 */
export function exportJianying(projectId, videoSetId) {
  return runAction(async () => {
    const res = await api.export.jianying(projectId, videoSetId)
    if (!res || res.ok === false) throw new Error((res && res.msg) || '未知原因')
    return res
  }, { success: res => res.msg || '已导出到剪映', error: '导出剪映失败' })
}

/** 写 CapCut 草稿并打开国际版 CapCut。后端失败时 HTTP 仍是 200，ok=false 带原因。 */
export function exportCapcut(projectId, videoSetId) {
  return runAction(async () => {
    const res = await api.export.capcut(projectId, videoSetId)
    if (!res || res.ok === false) throw new Error((res && res.msg) || '未知原因')
    return res
  }, { success: res => res.msg || '已导出到 CapCut', error: '导出 CapCut 失败' })
}

/** 生成整部作品的 SRT 字幕并下载 */
export async function downloadSrt(projectId) {
  const ok = await runAction(() => api.tts.exportSrt(projectId), {
    success: res => (res && res.message) || '字幕已生成',
    error: '字幕导出失败'
  })
  if (ok) window.open(api.tts.downloadSrt(projectId), '_blank')
  return ok
}
