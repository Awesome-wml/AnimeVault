<template>
  <section v-if="task" class="batch-progress" role="status" aria-live="polite" :aria-label="title">
    <div class="batch-progress__row">
      <span class="batch-progress__text">{{ summary }}</span>
      <div class="inline-actions">
        <BaseButton v-if="task.running" variant="text" :disabled="task.cancelled" @click="task.cancel()">
          {{ task.cancelled ? '正在停止…' : '取消' }}
        </BaseButton>
        <template v-else>
          <BaseButton v-if="task.failed.length" variant="secondary" @click="retry">重试失败项</BaseButton>
          <BaseButton variant="text" @click="close">关闭</BaseButton>
        </template>
      </div>
    </div>
    <div v-if="task.running" class="batch-progress__bar" aria-hidden="true">
      <span :style="{ width: percent + '%' }"></span>
    </div>
    <ul v-if="!task.running && task.failed.length" class="batch-progress__failed">
      <li v-for="(f, i) in task.failed" :key="i"><span class="batch-progress__name">{{ f.label }}</span>：{{ f.reason }}</li>
    </ul>
  </section>
</template>

<script>
/**
 * 批量任务进度条（配合 utils/batchRun）。页面只需：
 *   this.batch = batchRun(items, worker, opts)
 *   <BatchProgress :task.sync="batch" running-text="正在生成" done-text="参考图已生成" unit="张" />
 * - 运行中：“正在生成 x / n · 失败 m” + 取消
 * - 结束：全部成功则轻提示并收起；有失败则列出失败项和原因，可“重试失败项”
 * - 组件销毁（离开页面）时自动取消剩余
 */
import { progressText } from '@/utils/batchRun'
import { toastSuccess, toastInfo, toastWarning } from '@/utils/notify'
import BaseButton from './BaseButton.vue'

export default {
  name: 'BatchProgress',
  components: { BaseButton },
  props: {
    task: { type: Object, default: null },
    runningText: { type: String, default: '正在生成' },
    doneText: { type: String, default: '生成完成' },
    unit: { type: String, default: '张' },
    title: { type: String, default: '批量进度' }
  },
  computed: {
    percent() { return this.task && this.task.total ? Math.round((this.task.done / this.task.total) * 100) : 0 },
    summary() {
      const t = this.task
      if (t.running) return progressText(t, this.runningText)
      const ok = t.done - t.failed.length
      const head = t.cancelled ? `已取消：完成 ${ok} ${this.unit}，剩余 ${t.total - t.done} ${this.unit}未处理` : this.doneText
      return t.failed.length ? `${head}，${t.failed.length} ${this.unit}失败` : head
    }
  },
  watch: {
    'task.running'(now, before) {
      if (before && !now) this.finished()
    }
  },
  beforeDestroy() {
    if (this.task) this.task.cancel()
  },
  methods: {
    finished() {
      const t = this.task
      if (t.failed.length) {
        toastWarning(this.summary)
        return
      }
      if (t.cancelled) toastInfo(this.summary)
      else toastSuccess(`全部 ${t.total} ${this.unit}${this.doneText}`)
      this.close()
    },
    retry() { this.$emit('update:task', this.task.retry()) },
    close() { this.$emit('update:task', null) }
  }
}
</script>

<style scoped>
.batch-progress {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 10px 14px;
  border: 1px solid var(--line);
  border-radius: var(--radius);
  background: var(--surface);
}
.batch-progress__row { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 8px 16px; }
.batch-progress__text { font-size: var(--fs-body); color: var(--ink); }
.batch-progress__bar { height: 2px; background: var(--line); border-radius: 1px; overflow: hidden; }
.batch-progress__bar > span { display: block; height: 100%; background: var(--ink); transition: width var(--dur); }
.batch-progress__failed { margin: 0; padding: 0 0 0 18px; font-size: var(--fs-small); color: var(--seal); }
.batch-progress__name { font-weight: 500; }
@media (prefers-reduced-motion: reduce) {
  .batch-progress__bar > span { transition: none; }
}
</style>
