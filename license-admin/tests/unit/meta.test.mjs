// utils/meta.js：/meta 的整理与回退；utils/validators.js 的授权条款规则
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { normalizeMeta, buildPlanOptions } from '../../src/utils/meta.js'
import { licenseTermsRules } from '../../src/utils/validators.js'

const FB = { plans: ['trial', 'basic'], features: ['video'], pattern: /^[a-z0-9_]{1,40}$/, devMax: { min: 1, max: 100 } }

test('服务端返回合法 meta：套餐、功能点候选、格式规则、设备数范围都取服务端的', () => {
  const m = normalizeMeta({
    plans: ['trial', 'pro', 'vip'], features: { pattern: '^[a-z]{1,5}$', candidates: ['abc', 'ABC', 'toolong'] },
    dev_max: { min: 1, max: 5 }
  }, FB)
  assert.deepEqual(m.plans, [{ value: 'trial', label: '试用' }, { value: 'pro', label: '专业' }, { value: 'vip', label: 'vip' }])
  assert.deepEqual(m.featureOptions, ['abc'])           // 不符合格式的候选被丢弃
  assert.ok(m.featurePattern.test('abc') && !m.featurePattern.test('abcdef'))
  assert.deepEqual(m.devMax, { min: 1, max: 5 })
  assert.equal(m.fromServer, true)
})

test('meta 为空、失败或字段不合法时回退到兜底值', () => {
  for (const bad of [null, undefined, 'x', {}, { plans: [], features: null }, { plans: [1, 2], features: { pattern: '(' } }]) {
    const m = normalizeMeta(bad, FB)
    assert.deepEqual(m.plans, buildPlanOptions(FB.plans), JSON.stringify(bad))
    assert.deepEqual(m.featureOptions, FB.features)
    assert.equal(m.featurePattern, FB.pattern)
    assert.deepEqual(m.devMax, FB.devMax)
    assert.equal(m.fromServer, false)
  }
})

test('功能点格式只接受 ^...$ 且长度合理的正则，防止服务端异常数据拖垮前端', () => {
  assert.equal(normalizeMeta({ plans: ['a'], features: { pattern: 'abc' } }, FB).featurePattern, FB.pattern)
  assert.equal(normalizeMeta({ plans: ['a'], features: { pattern: '^' + 'a'.repeat(300) + '$' } }, FB).featurePattern, FB.pattern)
})

test('设备数范围不合法时用兜底', () => {
  assert.deepEqual(normalizeMeta({ plans: ['a'], dev_max: { min: 5, max: 2 } }, FB).devMax, FB.devMax)
  assert.deepEqual(normalizeMeta({ plans: ['a'], dev_max: { min: 0, max: 9 } }, FB).devMax, FB.devMax)
})

test('授权条款校验规则：功能点按传入格式校验，到期时间必填且不能早于今天', async () => {
  const rules = licenseTermsRules(() => /^[a-z]+$/)
  const run = (rule, value) => new Promise(resolve => rule.validator({}, value, err => resolve(err ? err.message : '')))
  assert.equal(await run(rules.features[0], ['ok']), '')
  assert.match(await run(rules.features[0], ['ok', 'Bad_1']), /Bad_1/)
  assert.equal(await run(rules.features[0], undefined), '')
  assert.match(await run(rules.expires[0], null), /请选择/)
  assert.match(await run(rules.expires[0], Date.now() - 3 * 86400000), /不能早于今天/)
  assert.equal(await run(rules.expires[0], Date.now() + 86400000), '')
  assert.equal(rules.plan[0].required, true)
})
