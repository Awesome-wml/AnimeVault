// L-45 管理端运营能力 e2e：申请单（客户端提交 -> 管理端出现 -> 签发/驳回）、设备页签（踢下线、解绑）、
// 角色可见性、审计页显示用户名、功能点候选来自服务端 /meta。依赖 admin.spec.js 之后运行（同一个内存服务）。
const path = require('path')
const { execFileSync } = require('child_process')
const { test, expect } = require('@playwright/test')

const PASSWORD = process.env.E2E_ADMIN_PASSWORD
const API_PORT = process.env.E2E_LICENSE_PORT || '18100'
const FRONT_PORT = process.env.E2E_FRONT_PORT || '5180'
const API = `http://127.0.0.1:${API_PORT}`
const SHOTS = path.join(__dirname, 'screenshots')
const ROOT = path.join(__dirname, '..', '..')

// 合成机器码：和真实机器码互不相同，避免与 admin.spec.js 里签发的授权撞在一起
function synthetic(seed) {
  const py = `
import json
from dongai_license.machine_code import format_machine_code
comps = [f"{${seed}:02x}{i:02x}" + "ab" * 6 for i in range(3)]
print(json.dumps({"code": format_machine_code(comps), "comps": comps}))`
  return JSON.parse(execFileSync('python3', ['-c', py], { env: { ...process.env, PYTHONPATH: path.join(ROOT, 'license') }, encoding: 'utf8' }))
}

function futureDate(days) {
  const d = new Date(Date.now() + days * 86400000)
  const p = n => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
}

function field(page, id) {
  return page.locator(`[data-testid="${id}"]`).locator('xpath=self::input | self::textarea | .//input | .//textarea').first()
}

async function login(page, username) {
  await page.goto('/login')
  await field(page, 'login-username').fill(username)
  await field(page, 'login-password').fill(PASSWORD)
  await page.getByTestId('login-submit').click()
  await expect(page.getByTestId('current-admin')).toContainText(username)
}

async function adminToken(request, username) {
  const r = await request.post(`${API}/admin/api/auth/login`, { data: { username, password: PASSWORD } })
  return { Authorization: 'Bearer ' + (await r.json()).token }
}

const clientRequest = (request, email, mc, note) =>
  request.post(`${API}/license/v1/request`, { data: { email, machine_code: mc.code, note } })

const activate = (request, code, comps) =>
  request.post(`${API}/license/v1/activate`, { data: { license_code: code, machine_components: comps, app_version: '9.9.9' } })

const renew = (request, lease, comps) =>
  request.post(`${API}/license/v1/renew`, { data: { lease, machine_components: comps, app_version: '9.9.9' } })

const visible = (page, id) => page.locator(`[data-testid="${id}"]:visible`)

const reqMc = synthetic(21)
const rejMc = synthetic(22)
const devMc = synthetic(23)
let issuedLid = ''
let deviceLid = ''

test.describe.configure({ mode: 'serial' })

test('客户端提交申请 -> ops 看到菜单角标和申请单 -> 签发 -> 授权列表出现，授权码可复制', async ({ page, request, context }) => {
  await context.grantPermissions(['clipboard-read', 'clipboard-write'], { origin: `http://127.0.0.1:${FRONT_PORT}` })
  expect((await clientRequest(request, 'req-buyer@example.com', reqMc, 'e2e 申请单')).ok()).toBeTruthy()
  // 同邮箱同机器码重复提交：只有一条
  expect((await clientRequest(request, 'REQ-buyer@example.com', reqMc, 'e2e 申请单')).ok()).toBeTruthy()
  expect((await clientRequest(request, 'req-reject@example.com', rejMc, '待驳回')).ok()).toBeTruthy()
  // 校验：机器码分量不足 / 邮箱不对
  const bad = await request.post(`${API}/license/v1/request`, { data: { email: 'x@example.com', machine_code: 'ABC' } })
  expect(bad.status()).toBe(422)

  await login(page, 'e2e_ops')
  await expect(page.getByTestId('menu-requests')).toBeVisible()
  await expect(page.getByTestId('menu-badge-requests')).toHaveText('2')
  await page.getByTestId('menu-requests').click()
  const table = page.getByTestId('request-table')
  await expect(table.locator('tr', { hasText: 'req-buyer@example.com' })).toHaveCount(1)
  await expect(table.locator('tr', { hasText: 'req-buyer@example.com' })).toContainText('待处理')
  await page.screenshot({ path: path.join(SHOTS, '05-requests.png') })

  // 签发
  await table.locator('tr', { hasText: 'req-buyer@example.com' }).locator('[data-testid^="req-issue-"]').click()
  await expect(field(page, 'request-issue-email')).toHaveValue('req-buyer@example.com')
  await expect(field(page, 'request-issue-mc')).toHaveValue(reqMc.code)
  await page.getByTestId('request-issue-submit').click()
  await expect(page.locator('.el-form-item__error').first()).toBeVisible()   // 未选套餐、到期时间：前端拦截
  await page.getByTestId('request-issue-plan').click()
  await page.locator('.el-select-dropdown__item:visible', { hasText: 'pro' }).click()
  // 功能点候选来自服务端 /meta（LS_FEATURES），不是前端常量
  await page.getByTestId('request-issue-features').click()
  await page.locator('.el-select-dropdown__item:visible', { hasText: 'e2e_feat' }).click()
  await page.keyboard.press('Escape')
  await field(page, 'request-issue-expires').fill(futureDate(60))
  await field(page, 'request-issue-expires').press('Enter')
  await page.getByTestId('request-issue-submit').click()
  const result = page.getByTestId('request-issue-result')
  await expect(result).toBeVisible()
  issuedLid = (await page.getByTestId('request-issued-lid').innerText()).trim()
  expect(issuedLid).toMatch(/^lic_/)
  await page.getByTestId('copy-code').click()
  await expect(page.getByTestId('copy-code')).toContainText('已复制')
  expect((await page.evaluate(() => navigator.clipboard.readText())).replace(/[\s-]/g, '').length).toBeGreaterThan(100)
  await page.getByTestId('request-issue-done').click()

  // 申请单消失（筛选待处理），角标减 1，已签发筛选里可见授权 ID
  await expect(table.locator('tr', { hasText: 'req-buyer@example.com' })).toHaveCount(0)
  await expect(page.getByTestId('menu-badge-requests')).toHaveText('1')
  await page.getByTestId('request-filter-status').click()
  await page.locator('.el-select-dropdown__item:visible', { hasText: '已签发' }).click()
  await expect(table.locator('tr', { hasText: 'req-buyer@example.com' })).toContainText(issuedLid)

  // 授权列表里出现这张授权
  await page.getByTestId('menu-licenses').click()
  await field(page, 'filter-email').fill('req-buyer@example.com')
  await page.getByTestId('search').click()
  await expect(page.locator('.el-table__body-wrapper tr', { hasText: issuedLid })).toContainText('待激活')
})

test('驳回申请单：需确认，驳回后不能再处理，角标清零', async ({ page }) => {
  await login(page, 'e2e_ops')
  await page.getByTestId('menu-requests').click()
  const row = page.getByTestId('request-table').locator('tr', { hasText: 'req-reject@example.com' })
  await row.locator('[data-testid^="req-reject-"]').click()
  await field(page, 'request-reject-reason').fill('信息不全')
  await visible(page, 'confirm-ok').click()
  await expect(row).toHaveCount(0)
  await expect(page.getByTestId('menu-badge-requests')).toHaveCount(0)
  await page.getByTestId('request-filter-status').click()
  await page.locator('.el-select-dropdown__item:visible', { hasText: '已驳回' }).click()
  await expect(row).toContainText('已驳回')
  await expect(row).toContainText('信息不全')
  await expect(row.locator('[data-testid^="req-issue-"]')).toHaveCount(0)
})

test('设备页签：踢下线（带确认）-> 续租收到会话冲突；重新激活后解绑（带确认）', async ({ page, request }) => {
  const h = await adminToken(request, 'e2e_ops')
  const r = await request.post(`${API}/admin/api/licenses`, {
    headers: h, data: { machine_code: devMc.code, plan: 'pro', features: [], expires_at: Math.floor(Date.now() / 1000) + 30 * 86400, email: 'dev@example.com' }
  })
  const lic = (await r.json()).license
  deviceLid = lic.lid
  const a1 = await activate(request, lic.code, devMc.comps)
  expect(a1.ok()).toBeTruthy()
  const lease1 = (await a1.json()).lease

  await login(page, 'e2e_ops')
  await field(page, 'filter-lid').fill(deviceLid)
  await page.getByTestId('search').click()
  await page.getByTestId('lid-' + deviceLid).click()
  const drawer = page.getByTestId('license-drawer')
  await drawer.getByRole('tab', { name: '设备' }).click()
  const panel = page.getByTestId('device-panel')
  await expect(panel.locator('tbody tr')).toHaveCount(1)
  await expect(panel).toContainText('当前在线')
  await expect(panel).toContainText('9.9.9')
  await expect(panel).toContainText('3 个分量')
  await expect(panel).not.toContainText(devMc.comps[0])           // 不显示分量全文，只显示前 6 位
  await expect(panel).toContainText(devMc.comps[0].slice(0, 6))
  await page.screenshot({ path: path.join(SHOTS, '06-devices.png') })

  // 踢下线：有确认说明
  await page.getByTestId('kick-open').click()
  await expect(visible(page, 'confirm-ok')).toBeVisible()
  await expect(page.locator('.el-dialog:visible')).toContainText('下次续租会被要求重新激活')
  await visible(page, 'confirm-ok').click()
  await expect(page.getByTestId('kick-open')).toBeDisabled()       // 已无在线会话
  await expect(panel).not.toContainText('当前在线')
  const rn = await renew(request, lease1, devMc.comps)
  expect(rn.status()).toBe(409)
  expect((await rn.json()).code).toBe('LICENSE_SESSION_CONFLICT')

  // 时间线显示操作人用户名
  await drawer.getByRole('tab', { name: '详情' }).click()
  await expect(page.getByTestId('event-timeline')).toContainText('踢下线')
  await expect(page.getByTestId('event-timeline')).toContainText('操作人 e2e_ops')

  // 重新激活 -> 解绑当前设备（同时踢下线）
  const a2 = await activate(request, lic.code, devMc.comps)
  expect(a2.ok()).toBeTruthy()
  const lease2 = (await a2.json()).lease
  await drawer.getByRole('tab', { name: '设备' }).click()
  await page.reload()
  await field(page, 'filter-lid').fill(deviceLid)
  await page.getByTestId('search').click()
  await page.getByTestId('lid-' + deviceLid).click()
  await page.getByTestId('license-drawer').getByRole('tab', { name: '设备' }).click()
  await expect(page.getByTestId('device-panel')).toContainText('当前在线')
  await page.locator('[data-testid^="unbind-"]').click()
  await expect(page.locator('.el-dialog:visible')).toContainText('同时把它踢下线')
  await visible(page, 'confirm-ok').click()
  await expect(page.getByTestId('device-panel')).toContainText('已解绑')
  await expect(page.locator('[data-testid^="unbind-"]')).toBeDisabled()
  expect((await renew(request, lease2, devMc.comps)).status()).toBe(409)
})

test('readonly：看不到申请单菜单、进不去；设备页签只读，没有踢下线和解绑按钮', async ({ page }) => {
  await login(page, 'e2e_readonly')
  await expect(page.getByTestId('menu-requests')).toHaveCount(0)
  await page.goto('/requests')
  await expect(page).toHaveURL(/\/licenses/)
  await field(page, 'filter-lid').fill(deviceLid)
  await page.getByTestId('search').click()
  await page.getByTestId('lid-' + deviceLid).click()
  await page.getByTestId('license-drawer').getByRole('tab', { name: '设备' }).click()
  await expect(page.getByTestId('device-panel')).toContainText('已解绑')
  await expect(page.getByTestId('kick-open')).toHaveCount(0)
  await expect(page.locator('[data-testid^="unbind-"]')).toHaveCount(0)
})

test('审计页显示操作人用户名；管理员列表分页控件随总数出现', async ({ page }) => {
  await login(page, 'e2e_super')
  await page.getByTestId('menu-audit').click()
  const body = page.locator('.el-table__body-wrapper .el-table__body').first()
  await expect(body).toContainText('踢下线')
  await expect(body).toContainText('解绑设备')
  await expect(body).toContainText('签发申请单')
  await expect(body.locator('tr', { hasText: '签发申请单' }).first()).toContainText('e2e_ops')
  await expect(body.locator('tr', { hasText: '驳回申请单' }).first()).toContainText('e2e_ops')
  await page.screenshot({ path: path.join(SHOTS, '07-audit-operator.png') })

  await page.getByTestId('menu-admins').click()
  await expect(page.locator('.base-table__pager')).toContainText('共')
})
