/**
 * 一键提取 / 拆分镜的分阶段进度：页面拿到一个响应式对象交给 <ExtractProgress :progress>。
 *   const task = extractTask()          // { running, stage, chunk, total, message, startedAt }
 *   task.stage = 'assets'               // 资产提取
 *   await withSplitProgress(task, pid, () => api.shot.split(...))   // 拆分镜，期间轮询“第 x/n 块”
 *   finishTask(task, '一键提取完成') / failTask(task, e, '拆分镜失败')
 */
import { api } from '@/api'

const POLL_MS = 3000

export function extractTask(stage = 'assets') {
  return { running: true, stage, chunk: 0, total: 0, message: '', startedAt: Date.now() }
}

/** 拆分镜阶段：调用期间每 3 秒读一次后端分块进度 */
export async function withSplitProgress(task, projectId, run) {
  task.stage = 'shots'
  let stopped = false
  const poll = async () => {
    while (!stopped) {
      await new Promise(resolve => setTimeout(resolve, POLL_MS))
      if (stopped) break
      try {
        const res = await api.shot.splitProgress(projectId)
        const p = res && res.data
        if (p && !stopped) {
          task.chunk = p.chunk
          task.total = p.total
        }
      } catch (e) {
        // 进度只是提示，读不到不影响拆分本身
      }
    }
  }
  poll()
  try {
    return await run()
  } finally {
    stopped = true
  }
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
