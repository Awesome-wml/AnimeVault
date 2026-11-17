// 版本发布 e2e：ops 新建草稿 -> 前端校验 -> 编辑 -> 发布 -> 详情抽屉与复制 -> 撤回（二次确认 + 强制线提示），
// readonly 只读，以及客户端 /update 与 activate 的 426 联动。依赖前面两个 spec 同一个内存服务，最后运行。
const path = require('path')
const { execFileSync } = require('child_process')
const { test, expect } = require('@playwright/test')

const PASSWORD = process.env.E2E_ADMIN_PASSWORD
const API_PORT = process.env.E2E_LICENSE_PORT || '18100'
const FRONT_PORT = process.env.E2E_FRONT_PORT || '5180'
const API = `http://127.0.0.1:${API_PORT}`
const SHOTS = path.join(__dirname, 'screenshots')
const ROOT = path.join(__dirname, '..', '..')
const SHA = 'ab'.repeat(32)

function synthetic(seed) {
  const py = `
import json
from dongai_license.machine_code import format_machine_code
comps = [f"{${seed}:02x}{i:02x}" + "ab" * 6 for i in range(3)]
print(json.dumps({"code": format_machine_code(comps), "comps": comps}))`
  return JSON.parse(execFileSync('python3', ['-c', py], { env: { ...process.env, PYTHONPATH: path.join(ROOT, 'license') }, encoding: 'utf8' }))
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

const update = (request, version, extra = '') =>
  request.get(`${API}/license/v1/update?version=${encodeURIComponent(version)}&platform=win-x64${extra}`).then(r => r.json())

async function pick(page, testid, text) {
  await page.getByTestId(testid).click()
  await page.locator('.el-select-dropdown__item:visible', { hasText: text }).click()
}

async function fillForm(page, v) {
  await field(page, 'release-version').fill(v.version)
  await pick(page, 'release-platform', 'Windows 64 位')
  await field(page, 'release-url').fill(v.url)
  await field(page, 'release-sha256').fill(v.sha256 || SHA)
  await field(page, 'release-size').fill(String(v.size || 52428800))
  await field(page, 'release-min').fill(v.min || '')
  await field(page, 'release-notes').fill(v.notes || '')
}

// 按版本号列精确匹配（强制升级线列也会出现版本号，不能用 hasText 模糊匹配）
const rowOf = (page, version) => page.getByTestId('release-table').locator('tr').filter({ has: page.locator('[data-testid^="rel-version-"]', { hasText: new RegExp('^' + version.replace(/\./g, '\\.') + '$') }) })

test.describe.configure({ mode: 'serial' })

test('ops：新建草稿（前端校验）-> 编辑 -> 发布 -> 详情抽屉复制 -> /update 可见', async ({ page, request, context }) => {
  await context.grantPermissions(['clipboard-read', 'clipboard-write'], { origin: `http://127.0.0.1:${FRONT_PORT}` })
  await login(page, 'e2e_ops')
  await page.getByTestId('menu-releases').click()
  await expect(page.getByTestId('release-table')).toBeVisible()
  await expect(page.getByTestId('release-new')).toBeVisible()

  // 前端校验：http 地址、非法 sha256、强制线高于版本
  await page.getByTestId('release-new').click()
  await fillForm(page, { version: '1.0.0', url: 'http://dl.example.com/a.exe', sha256: 'xyz', min: '2.0.0', notes: '首个版本' })
  await page.getByTestId('release-submit').click()
  await expect(page.locator('.el-form-item__error:visible', { hasText: 'https' })).toBeVisible()
  await expect(page.locator('.el-form-item__error:visible', { hasText: '64 位十六进制' })).toBeVisible()
  await expect(page.locator('.el-form-item__error:visible', { hasText: '不能高于' })).toBeVisible()

  // 改对后创建
  await field(page, 'release-url').fill('https://dl.example.com/dongai-1.0.0.exe')
  await field(page, 'release-sha256').fill(SHA)
  await field(page, 'release-min').fill('')
  await page.getByTestId('release-submit').click()
  await expect(rowOf(page, '1.0.0')).toContainText('草稿')
  expect((await update(request, '0.1.0')).latest).toBeNull() // 草稿客户端不可见

  // 编辑草稿：改更新说明
  await rowOf(page, '1.0.0').locator('[data-testid^="rel-edit-"]').click()
  await expect(field(page, 'release-version')).toHaveValue('1.0.0')
  await field(page, 'release-notes').fill('修复若干问题\n优化启动速度')
  await page.getByTestId('release-submit').click()
  await expect(page.getByTestId('release-submit')).toBeHidden()

  // 再建一个带强制线的 1.1.0（版本号字符串比较会排在 1.0.0 前后混乱，这里验证数字比较）
  await page.getByTestId('release-new').click()
  await fillForm(page, { version: '1.10.0', url: 'https://dl.example.com/dongai-1.10.0.exe', min: '1.0.0', notes: '新增版本管理' })
  await page.getByTestId('release-submit').click()
  await expect(rowOf(page, '1.10.0')).toContainText('草稿')
  // 同版本号重复：服务端拒绝
  await page.getByTestId('release-new').click()
  await fillForm(page, { version: '1.10.0+build9', url: 'https://dl.example.com/x.exe' })
  await page.getByTestId('release-submit').click()
  await expect(page.locator('.el-message--error', { hasText: '相同版本号' })).toBeVisible()
  await page.getByRole('button', { name: '取消' }).click()

  // 发布 1.0.0（有确认弹窗）
  await rowOf(page, '1.0.0').locator('[data-testid^="rel-publish-"]').click()
  await page.locator('[data-testid="confirm-ok"]:visible').click()
  await expect(rowOf(page, '1.0.0')).toContainText('已发布')
  await expect(rowOf(page, '1.0.0').locator('[data-testid^="rel-edit-"]')).toHaveCount(0) // 已发布不可编辑
  const u = await update(request, '0.9.0')
  expect(u).toMatchObject({ update_available: true, force: false, min_supported: null })
  expect(u.latest).toMatchObject({ version: '1.0.0', sha256: SHA, notes: '修复若干问题\n优化启动速度' })

  // 详情抽屉：更新说明、sha256、下载地址可复制
  await rowOf(page, '1.0.0').locator('[data-testid^="rel-detail-"]').click()
  await expect(page.getByTestId('drawer-notes')).toContainText('优化启动速度')
  await expect(page.getByTestId('drawer-sha256')).toHaveText(SHA)
  await page.getByTestId('copy-url').click()
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe('https://dl.example.com/dongai-1.0.0.exe')
  await page.getByTestId('copy-sha256').click()
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(SHA)
  await page.screenshot({ path: path.join(SHOTS, '10-release-drawer.png') })
  await page.keyboard.press('Escape')

  // 发布 1.10.0（强制线 1.0.0）：1.10.0 > 1.0.0，且低于 1.0.0 的客户端被强制
  await rowOf(page, '1.10.0').locator('[data-testid^="rel-publish-"]').click()
  await page.locator('[data-testid="confirm-ok"]:visible').click()
  await expect(rowOf(page, '1.10.0')).toContainText('已发布')
  await expect(page.locator('.release-notice')).toContainText('强制升级线变为 1.0.0')
  await expect(rowOf(page, '1.10.0')).toContainText('1.0.0')
  await page.waitForTimeout(700) // 等弹窗淡出再截图
  await page.screenshot({ path: path.join(SHOTS, '09-releases.png') })
  const f = await update(request, '0.9.0')
  expect(f).toMatchObject({ force: true, min_supported: '1.0.0', update_available: true })
  expect(f.latest.version).toBe('1.10.0')
  expect((await update(request, '1.0.0')).force).toBe(false)
  expect((await update(request, '1.10.0+testbuild')).update_available).toBe(false)
  expect((await update(request, '0.9.0', '&channel=beta')).latest).toBeNull() // 渠道隔离
})

test('客户端：低于强制升级线激活/续租返回 426，老客户端放行，撤回后恢复', async ({ page, request }) => {
  const mc = synthetic(31)
  const h = await adminToken(request, 'e2e_ops')
  const exp = Math.floor(Date.now() / 1000) + 86400 * 30
  const issued = await request.post(`${API}/admin/api/licenses`, { headers: h, data: { machine_code: mc.code, plan: 'pro', features: [], expires_at: exp, email: 'ver-e2e@example.com' } })
  expect(issued.status()).toBe(201)
  const code = (await issued.json()).license.code
  const act = (extra) => request.post(`${API}/license/v1/activate`, { data: { license_code: code, machine_components: mc.comps, ...extra } })

  const low = await act({ app_version: '0.9.0', platform: 'win-x64', channel: 'stable' })
  expect(low.status()).toBe(426)
  expect(await low.json()).toMatchObject({ code: 'UPDATE_REQUIRED', min_supported: '1.0.0' })
  const ok = await act({ app_version: '1.0.0+testbuild', platform: 'win-x64' })
  expect(ok.status()).toBe(200)
  const lease = (await ok.json()).lease
  const renew = (extra) => request.post(`${API}/license/v1/renew`, { data: { lease, machine_components: mc.comps, ...extra } })
  expect((await renew({ app_version: '0.9.0', platform: 'win-x64' })).status()).toBe(426)
  expect((await renew({ app_version: '0.9.0' })).status()).toBe(200) // 老客户端不带 platform：不拦截
  expect((await act({ app_version: '0.9.0' })).status()).toBe(200) // 激活同理（会顶掉上面的会话，之后不再续租）

  // 撤回带强制线的 1.10.0（唯一来源）：界面二次确认并提示，强制线消失，426 解除
  await login(page, 'e2e_ops')
  await page.getByTestId('menu-releases').click()
  await rowOf(page, '1.10.0').locator('[data-testid^="rel-withdraw-"]').click()
  await expect(page.getByRole('dialog', { name: '撤回版本' })).toContainText('不可恢复')
  await page.getByRole('button', { name: '取消' }).click()
  await expect(rowOf(page, '1.10.0')).toContainText('已发布') // 取消不撤回
  await rowOf(page, '1.10.0').locator('[data-testid^="rel-withdraw-"]').click()
  await page.locator('[data-testid="confirm-ok"]:visible').click()
  await expect(rowOf(page, '1.10.0')).toContainText('已撤回')
  await expect(page.locator('.release-notice')).toContainText('强制升级线变为 无')
  await expect(rowOf(page, '1.10.0').locator('[data-testid^="rel-withdraw-"]')).toHaveCount(0) // 终态
  expect((await update(request, '0.9.0')).force).toBe(false)
  expect((await update(request, '0.9.0')).latest.version).toBe('1.0.0')
  expect((await act({ app_version: '0.9.0', platform: 'win-x64' })).status()).toBe(200)

  // 审计页有版本相关记录
  await page.getByTestId('menu-audit').click()
  await expect(page.locator('td', { hasText: '撤回版本' }).first()).toBeVisible()
})

test('readonly：能看列表和详情，没有任何写操作入口，直接调写接口 403', async ({ page, request }) => {
  await login(page, 'e2e_readonly')
  await expect(page.getByTestId('menu-releases')).toBeVisible()
  await page.getByTestId('menu-releases').click()
  await expect(rowOf(page, '1.0.0')).toContainText('已发布')
  await expect(page.getByTestId('release-new')).toHaveCount(0)
  await expect(page.locator('[data-testid^="rel-edit-"], [data-testid^="rel-publish-"], [data-testid^="rel-withdraw-"]')).toHaveCount(0)
  await rowOf(page, '1.0.0').locator('[data-testid^="rel-detail-"]').click()
  await expect(page.getByTestId('drawer-sha256')).toHaveText(SHA)
  await expect(page.getByTestId('drawer-edit')).toHaveCount(0)
  await expect(page.getByTestId('drawer-withdraw')).toHaveCount(0)
  await expect(page.getByTestId('copy-url')).toBeVisible()
  const h = await adminToken(request, 'e2e_readonly')
  const r = await request.post(`${API}/admin/api/releases`, { headers: h, data: { version: '9.9.9', channel: 'stable', platform: 'win-x64', url: 'https://x.example.com/a', sha256: SHA, size: 1 } })
  expect(r.status()).toBe(403)
})
