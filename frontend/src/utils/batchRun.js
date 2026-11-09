/**
 * 通用批量执行器：对一组 items 逐个调用 worker(item)，全项目的“一键批量”都走这里
 * （配音、资产参考图、分镜画面）。
 *
 *   const task = batchRun(items, item => api.xxx(item), {
 *     concurrency: 1,              // 默认串行：出图接口有限流
 *     label: item => item.name,    // 失败列表里显示的名字
 *     onItemDone: (item, res) => {}, // 每完成一条立即回调（刷新对应卡片）
 *     onProgress: task => {}
 *   })
 *   task.cancel()                 // 不再派发新的；已在请求中的会等它返回
 *   await task.promise            // 结束（完成或取消）后 resolve 为 task 本身，不会 reject
 *   task.retry()                  // 用同样的 worker/选项重跑失败项，返回新的 task
 *
 * task 是普通对象，放进组件 data 后计数字段（done/failed/running）会响应式更新。
 */
export function batchRun(items, worker, options = {}) {
  const list = Array.from(items || [])
  const concurrency = Math.max(1, Number(options.concurrency) || 1)
  const label = options.label || (item => String(item))

  const task = {
    total: list.length,
    done: 0,
    /** [{ item, label, reason }] */
    failed: [],
    running: list.length > 0,
    cancelled: false,
    promise: null,
    cancel() {
      if (!task.running) return
      task.cancelled = true
    },
    retry() {
      return batchRun(task.failed.map(f => f.item), worker, options)
    }
  }

  const notify = () => { if (options.onProgress) options.onProgress(task) }

  let next = 0
  async function lane() {
    while (!task.cancelled && next < list.length) {
      const item = list[next++]
      try {
        const res = await worker(item)
        if (options.onItemDone) options.onItemDone(item, res)
      } catch (e) {
        task.failed.push({ item, label: label(item), reason: reasonOf(e) })
      }
      task.done++
      notify()
    }
  }

  task.promise = Promise.all(Array.from({ length: Math.min(concurrency, list.length) }, lane))
    .then(() => {
      task.running = false
      notify()
      return task
    })
  return task
}

/** 失败原因：后端 detail（拦截器已放进 message）或异常文字 */
function reasonOf(e) {
  if (!e) return '未知错误'
  const detail = e.response && e.response.data && e.response.data.detail
  if (typeof detail === 'string' && detail) return detail
  return e.message || String(e)
}

/** 进度文字：“正在生成 2 / 5 · 失败 1”。按钮和进度条共用 */
export function progressText(task, prefix = '正在生成') {
  if (!task) return ''
  const failed = task.failed.length ? ` · 失败 ${task.failed.length}` : ''
  return `${prefix} ${task.done} / ${task.total}${failed}`
}

/** 是否正在跑（页面据此禁用按钮） */
export function isRunning(task) {
  return !!(task && task.running)
}
