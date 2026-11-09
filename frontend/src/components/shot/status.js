/**
 * 分镜状态。后端目前只能区分“有没有视频”，生成中进度来自 SSE（/api/video/events）。
 * 审核状态（待审核/已通过/失败）需要后端支持，暂不显示。
 */
export function shotStatus(shot, progress) {
  if (progress && progress.step && progress.step !== 'done') {
    return { status: 'shot_generating', n: progress.progress || 0 }
  }
  if (shot.video_path) return { status: 'shot_has_video' }
  return { status: 'shot_no_video' }
}

/** 说话人：分镜的 character_name，空则为旁白 */
export const NARRATOR = '旁白'
export function speakerOf(shot) {
  return shot.character_name || NARRATOR
}
