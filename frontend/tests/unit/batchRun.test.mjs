// utils/batchRun 单元测试：node --test（npm run test:unit）
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { batchRun, progressText } from '../../src/utils/batchRun.js'

const sleep = ms => new Promise(r => setTimeout(r, ms))

test('默认串行：按顺序逐个执行，回调每条完成', async () => {
  const order = []
  let active = 0
  let maxActive = 0
  const done = []
  const task = batchRun([1, 2, 3], async n => {
    active++; maxActive = Math.max(maxActive, active)
    order.push(n)
    await sleep(5)
    active--
    return n * 10
  }, { onItemDone: (n, res) => done.push([n, res]) })
  assert.equal(task.running, true)
  await task.promise
  assert.deepEqual(order, [1, 2, 3])
  assert.equal(maxActive, 1)
  assert.deepEqual(done, [[1, 10], [2, 20], [3, 30]])
  assert.equal(task.done, 3)
  assert.equal(task.running, false)
})

test('并发上限生效', async () => {
  let active = 0
  let maxActive = 0
  const task = batchRun([1, 2, 3, 4, 5], async () => {
    active++; maxActive = Math.max(maxActive, active)
    await sleep(5)
    active--
  }, { concurrency: 2 })
  await task.promise
  assert.equal(maxActive, 2)
  assert.equal(task.done, 5)
})

test('失败收集原因，不中断后续；重试只跑失败项', async () => {
  let failOnce = true
  const task = batchRun(['a', 'b', 'c'], async x => {
    if (x === 'b' && failOnce) { failOnce = false; throw Object.assign(new Error('x'), { response: { data: { detail: '限流' } } }) }
  }, { label: x => `项 ${x}` })
  await task.promise
  assert.equal(task.done, 3)
  assert.deepEqual(task.failed.map(f => [f.label, f.reason]), [['项 b', '限流']])
  assert.equal(progressText(task), '正在生成 3 / 3 · 失败 1')
  const again = task.retry()
  assert.equal(again.total, 1)
  await again.promise
  assert.equal(again.failed.length, 0)
})

test('取消：不再派发新的，已在跑的等它返回', async () => {
  const seen = []
  const task = batchRun([1, 2, 3, 4], async n => { seen.push(n); await sleep(10) })
  await sleep(2)
  task.cancel()
  await task.promise
  assert.deepEqual(seen, [1])
  assert.equal(task.done, 1)
  assert.equal(task.cancelled, true)
  assert.equal(task.running, false)
})

test('空列表直接结束', async () => {
  const task = batchRun([], async () => {})
  assert.equal(task.running, false)
  await task.promise
  assert.equal(task.total, 0)
})
