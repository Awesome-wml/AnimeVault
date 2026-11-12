/**
 * 一键提取 / 拆分镜的分阶段进度：页面拿到一个响应式对象交给 <ExtractProgress :progress>。
 *   const task = extractTask()          // { running, stage, chunk, total, message, startedAt }
 *   task.stage = 'assets'               // 资产提取（SSE，onProgress 写 task.chars）
 *   await api.shot.split(params, onProgress)   // 拆分镜（SSE，onProgress 写 task.chunk/total）
 *   finishTask(task, '一键提取完成') / failTask(task, e, '拆分镜失败')
 */

export function extractTask(stage = 'assets') {
  return { running: true, stage, chars: 0, chunk: 0, total: 0, message: '', startedAt: Date.now() }
}

export function finishTask(task, message) {
  task.running = false
  task.stage = 'done'
  task.message = message
}

/** 失败：显示后端给的原因（如“小说片段过长，模型输出被截断，请缩短或换模型”） */
export function failTask(task, error, fallback) {
  task.running = false
  task.stage = 'failed'
  const reason = (error && (error.reason || error.message)) || ''
  task.message = reason ? `${fallback}：${reason}` : fallback
}
