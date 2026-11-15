/**
 * 分镜状态。后端目前只能区分“有没有视频”，生成中进度来自 SSE（/api/video/events）。
 * 审核状态（待审核/已通过/失败）需要后端支持，暂不显示。
 */
export function shotStatus(shot, progress) {
  // 成片优先：已挂回视频就显示已出视频，SSE 残留的生成进度不能压住成片状态
  if (shot.video_path) return { status: 'shot_has_video' }
  // 终态失败：按后端 code 区分风控拦截与服务端生成失败，reason 为具体原因片段
  if (progress && progress.step === 'failed') {
    const code = progress.code || ''
    const status = code === 'REJECTED' ? 'shot_rejected'
      : code === 'GEN_FAILED' ? 'shot_gen_failed'
      : 'shot_failed'
    return { status, code, reason: progress.reason || progress.msg || '', msg: progress.msg }
  }
  if (progress && progress.step && progress.step !== 'done') {
    return { status: 'shot_generating', n: progress.progress || 0 }
  }
  return { status: 'shot_no_video' }
}

/** 说话人：分镜的 character_name，空则为旁白 */
export const NARRATOR = '旁白'
export function speakerOf(shot) {
  return shot.character_name || NARRATOR
}
