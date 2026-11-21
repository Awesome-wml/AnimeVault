/** 覆盖重拆前的提示文案：后端拆分镜会删掉本集全部旧镜头（含已出视频引用）再重编号。没有镜头时返回空串。 */
export function resplitMessage(shots, where = '当前剧集') {
  const total = shots.length
  const withVideo = shots.filter(s => s && s.video_path).length
  if (!total) return ''
  const videoPart = withVideo ? `，其中 ${withVideo} 个已出视频，重拆后这些视频不再挂在镜头上，需要重新生成（会再次消耗额度）` : ''
  return `重新拆分镜会删除${where}现有的 ${total} 个镜头${videoPart}。此操作不能撤销。`
}
