// 授权：api/license.js 错误映射、路由守卫逻辑（utils/licenseGate.js）、本地令牌、展示函数
import { test } from 'node:test'
import assert from 'node:assert/strict'
import {
  licenseErrorCode, licenseErrorMessage, isLicenseRequired, isLicenseUrl, createLicenseApi, LICENSE_ERROR_MESSAGES
} from '../../src/api/license.js'
import {
  resolveLicenseRoute, createLicenseGate, isAuthorized, ACTIVATE_PATH, HOME_PATH, STATUS_TTL_MS
} from '../../src/utils/licenseGate.js'
import { getLocalToken, localTokenHeaders, LOCAL_TOKEN_HEADER } from '../../src/utils/localToken.js'
import { planLabel, stateLabel, formatExpiry, daysLeft } from '../../src/components/license/license.js'

const httpError = (status, data) => ({ response: { status, data } })

test('错误映射：按 code 给中文提示', () => {
  assert.equal(licenseErrorMessage(httpError(400, { code: 'LICENSE_INVALID' })), LICENSE_ERROR_MESSAGES.LICENSE_INVALID)
  assert.match(licenseErrorMessage(httpError(403, { code: 'LICENSE_MACHINE_MISMATCH' })), /不是本机的授权码|不是本机/)
  assert.match(licenseErrorMessage(httpError(403, { code: 'LICENSE_EXPIRED' })), /已过期/)
  assert.match(licenseErrorMessage(httpError(503, { code: 'MACHINE_CODE_UNAVAILABLE' })), /硬件信息/)
})

test('错误映射：未知 code 用后端 message，网络错误与兜底', () => {
  assert.equal(licenseErrorMessage(httpError(500, { code: 'X', message: '后端说明' })), '后端说明')
  assert.match(licenseErrorMessage({ message: 'Network Error' }), /无法连接/)
  assert.match(licenseErrorMessage(httpError(500, {})), /激活失败/)
  assert.equal(licenseErrorCode(null), '')
})

test('isLicenseRequired / isLicenseUrl', () => {
  assert.equal(isLicenseRequired(httpError(403, { code: 'LICENSE_REQUIRED', state: 'unactivated' })), true)
  assert.equal(isLicenseRequired(httpError(403, { detail: '未认证' })), false)
  assert.equal(isLicenseRequired(httpError(401, { code: 'LICENSE_REQUIRED' })), false)
  assert.equal(isLicenseRequired(null), false)
  assert.equal(isLicenseUrl('/api/license/activate'), true)
  assert.equal(isLicenseUrl('/api/license/status'), true)
  assert.equal(isLicenseUrl('/api/projects'), false)
  assert.equal(isLicenseUrl('/api/licensex'), false)
})

test('createLicenseApi 走注入的 service', async () => {
  const calls = []
  const svc = { get: async u => calls.push(['get', u]), post: async (u, b) => calls.push(['post', u, b]) }
  const api = createLicenseApi(svc)
  await api.machineCode(); await api.status(); await api.activate('ABC'); await api.deactivate()
  assert.deepEqual(calls, [
    ['get', '/api/license/machine-code'], ['get', '/api/license/status'],
    ['post', '/api/license/activate', { code: 'ABC' }], ['post', '/api/license/deactivate', undefined]
  ])
})

test('路由决策：未授权只能去激活页，已授权离开激活页，未知状态放行', () => {
  const bad = { state: 'unactivated' }
  const ok = { state: 'valid' }
  assert.equal(resolveLicenseRoute('/home', bad), ACTIVATE_PATH)
  assert.equal(resolveLicenseRoute('/login', bad), ACTIVATE_PATH)
  assert.equal(resolveLicenseRoute('/', { state: 'expired' }), ACTIVATE_PATH)
  assert.equal(resolveLicenseRoute(ACTIVATE_PATH, bad), null)
  assert.equal(resolveLicenseRoute('/home', ok), null)
  assert.equal(resolveLicenseRoute(ACTIVATE_PATH, ok), HOME_PATH)
  assert.equal(resolveLicenseRoute('/home', null), null)
  assert.equal(resolveLicenseRoute(ACTIVATE_PATH, null), null)
  assert.equal(isAuthorized({ state: 'machine_mismatch' }), false)
})

test('守卫节流：TTL 内不重复请求，过期后再请求，invalidate/force 立即重查', async () => {
  let n = 0
  let t = 1000
  const gate = createLicenseGate({ fetchStatus: async () => ({ state: 'valid', n: ++n }), now: () => t })
  assert.equal((await gate.check()).n, 1)
  t += STATUS_TTL_MS - 1
  assert.equal((await gate.check()).n, 1)
  t += 2
  assert.equal((await gate.check()).n, 2)
  gate.invalidate()
  assert.equal((await gate.check()).n, 3)
  assert.equal((await gate.check({ force: true })).n, 4)
})

test('守卫：并发请求合并；失败返回 null 且不缓存', async () => {
  let n = 0
  let fail = true
  const gate = createLicenseGate({
    fetchStatus: async () => { n++; if (fail) throw new Error('down'); return { state: 'unactivated' } }
  })
  const [a, b] = await Promise.all([gate.check(), gate.check()])
  assert.equal(a, null); assert.equal(b, null); assert.equal(n, 1)
  fail = false
  assert.deepEqual(await gate.check(), { state: 'unactivated' })
  gate.set({ state: 'valid' })
  assert.equal((await gate.check()).state, 'valid')
  assert.equal(n, 2)
})

test('本地令牌：两种注入方式，没有就不加头', () => {
  assert.equal(getLocalToken({}), '')
  assert.deepEqual(localTokenHeaders({}), {})
  assert.equal(getLocalToken({ __DONGAI_LOCAL_TOKEN__: ' abc ' }), 'abc')
  assert.deepEqual(localTokenHeaders({ dongaiDesktop: { localToken: 'xyz' } }), { [LOCAL_TOKEN_HEADER]: 'xyz' })
  assert.equal(getLocalToken({ __DONGAI_LOCAL_TOKEN__: 'first', dongaiDesktop: { localToken: 'second' } }), 'first')
  assert.equal(getLocalToken({ dongaiDesktop: {} }), '')
  assert.equal(getLocalToken({ __DONGAI_LOCAL_TOKEN__: 123 }), '')
  assert.equal(LOCAL_TOKEN_HEADER, 'X-DongAI-Local-Token')
})

test('展示函数', () => {
  assert.equal(planLabel('pro'), '专业版')
  assert.equal(planLabel('custom'), 'custom')
  assert.equal(planLabel(null), '—')
  assert.equal(stateLabel('expired'), '已过期')
  assert.equal(stateLabel('zzz'), '未知')
  assert.equal(formatExpiry(null), '—')
  assert.match(formatExpiry(1798675200), /^\d{4}-\d{2}-\d{2}$/)
  assert.equal(daysLeft(null), null)
  assert.equal(daysLeft(2 * 86400 + 10, 0), 2)
  assert.ok(daysLeft(-5, 0) < 0)
})
