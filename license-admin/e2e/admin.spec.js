// 授权管理端 e2e：登录 -> 签发 -> 列表 -> 详情 -> 停用 -> 吊销；角色可见性。
// 各步共享同一份服务端状态，必须串行。
const path = require('path')
const { execFileSync } = require('child_process')
const { test, expect } = require('@playwright/test')

const PASSWORD = process.env.E2E_ADMIN_PASSWORD
const API = 'http://127.0.0.1:18100'
const SHOTS = path.join(__dirname, 'screenshots')
const ROOT = path.join(__dirname, '..', '..')

// 用共享库生成本机真实机器码
function realMachineCode() {
  const out = execFileSync('python3', ['-c', 'from dongai_license.machine_code import get_machine_code; print(get_machine_code())'], {
    env: { ...process.env, PYTHONPATH: path.join(ROOT, 'license') }, encoding: 'utf8'
  })
  return out.trim()
}

function futureDate(days) {
  const d = new Date(Date.now() + days * 86400000)
  const p = n => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
}

// Element 的 el-input 会把 data-testid 放在内部的 input/textarea 上，el-select、日期选择则在外层，这里统一取到可输入的元素
function field(page, id) {
  return page.locator(`[data-testid="${id}"]`).locator('xpath=self::input | self::textarea | .//input | .//textarea').first()
}

async function login(page, username, password = PASSWORD) {
  await page.goto('/login')
  await field(page, 'login-username').fill(username)
  await field(page, 'login-password').fill(password)
  await page.getByTestId('login-submit').click()
}

let lid = ''
let machineCode = ''

test.describe.configure({ mode: 'serial' })

test.beforeAll(() => { machineCode = realMachineCode() })

test('未登录访问列表会回到登录页', async ({ page }) => {
  await page.goto('/licenses')
  await expect(page).toHaveURL(/\/login/)
})

test('登录失败：显示中文错误，不进入系统', async ({ page }) => {
  await login(page, 'e2e_super', 'wrong-password-123')
  await expect(page.getByTestId('login-error')).toContainText('用户名或密码错误')
  await expect(page).toHaveURL(/\/login/)
  await page.screenshot({ path: path.join(SHOTS, '01-login.png') })
})

test('连续失败会被锁定并显示锁定提示', async ({ page }) => {
  for (let i = 0; i < 5; i++) {
    await login(page, 'e2e_locktest', 'wrong-password-123')
    await expect(page.getByTestId('login-error')).toBeVisible()
  }
  await login(page, 'e2e_locktest', 'wrong-password-123')
  await expect(page.getByTestId('login-error')).toContainText('锁定')
  await expect(page.getByTestId('login-submit')).toBeDisabled()
})

test('super 登录成功，进入授权列表，凭据在 sessionStorage 而不是 localStorage', async ({ page }) => {
  await login(page, 'e2e_super')
  await expect(page).toHaveURL(/\/licenses/)
  await expect(page.getByTestId('current-admin')).toContainText('e2e_super')
  await expect(page.getByTestId('current-role')).toContainText('超级管理员')
  const [ses, loc] = await page.evaluate(() => [Object.keys(sessionStorage).length, Object.keys(localStorage).length])
  expect(ses).toBeGreaterThan(0)
  expect(loc).toBe(0)
  for (const m of ['menu-licenses', 'menu-audit', 'menu-admins']) await expect(page.getByTestId(m)).toBeVisible()
})

test('签发：机器码初检、提交、展示授权码并可复制', async ({ page, context }) => {
  await context.grantPermissions(['clipboard-read', 'clipboard-write'], { origin: 'http://127.0.0.1:5180' })
  await login(page, 'e2e_super')
  await page.getByTestId('open-issue').click()

  // 格式不对时前端先提示
  await field(page, 'issue-machine-code').fill('ABC-89')
  await field(page, 'issue-machine-code').blur()
  await expect(page.getByTestId('mc-hint')).toContainText('无效字符')

  await field(page, 'issue-machine-code').fill(machineCode.toLowerCase().replace(/-/g, '  '))
  await field(page, 'issue-machine-code').blur()
  await expect(page.getByTestId('mc-hint')).toContainText('格式正常')

  await field(page, 'issue-email').fill('buyer@example.com')
  await page.getByTestId('issue-plan').click()
  await page.locator('.el-select-dropdown__item:visible', { hasText: 'pro' }).click()
  await field(page, 'issue-expires').fill(futureDate(30))
  await field(page, 'issue-expires').press('Enter')
  await page.getByTestId('issue-submit').click()

  const result = page.getByTestId('issue-result')
  await expect(result).toBeVisible()
  await expect(page.getByTestId('license-code')).toContainText('-')
  await expect(result).toContainText('可在详情中再次查看')
  lid = (await result.locator('b.mono').first().innerText()).trim()
  expect(lid).toMatch(/^lic_/)

  await page.getByTestId('copy-code').click()
  await expect(page.getByTestId('copy-code')).toContainText('已复制')
  const copied = await page.evaluate(() => navigator.clipboard.readText())
  expect(copied.replace(/[\s-]/g, '').length).toBeGreaterThan(100)
  await page.screenshot({ path: path.join(SHOTS, '03-issue-success.png') })

  // 再签发同一机器码：出现黄色提示，不阻止
  await page.getByTestId('issue-done').click()
  await page.getByTestId('open-issue').click()
  await field(page, 'issue-machine-code').fill(machineCode)
  await page.getByTestId('issue-plan').click()
  await page.locator('.el-select-dropdown__item:visible', { hasText: 'basic' }).click()
  await field(page, 'issue-expires').fill(futureDate(5))
  await field(page, 'issue-expires').press('Enter')
  await page.getByTestId('issue-submit').click()
  await expect(page.getByTestId('issue-warning')).toContainText('已有 1 条')
  await page.getByTestId('issue-done').click()
})

test('列表出现 pending，临近到期高亮；详情可看授权码；pending 不能停用', async ({ page }) => {
  await login(page, 'e2e_super')
  const row = page.locator('.el-table__body-wrapper tr', { hasText: lid })
  await expect(row).toContainText('待激活')
  await expect(row).toContainText('未激活')
  await expect(row.locator('.status-tag')).toHaveAttribute('data-status', 'pending')
  // 第二条是 5 天后到期的 basic：带「临近」标记
  await expect(page.locator('.expiry-flag')).toHaveCount(1)
  await page.screenshot({ path: path.join(SHOTS, '02-license-list.png') })

  // 1280 宽下页面不横向溢出
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
  expect(overflow).toBeLessThanOrEqual(0)
  const inner = await page.evaluate(() => { const w = document.querySelector('.el-table__body-wrapper'); return w.scrollWidth - w.clientWidth })
  expect(inner).toBeLessThanOrEqual(0)   // 表格自身也不横向滚动

  await page.getByTestId('lid-' + lid).click()
  const drawer = page.getByTestId('license-drawer')
  await expect(drawer).toContainText(lid)
  await expect(drawer).toContainText('绑定机器码分量')
  await expect(drawer.getByTestId('event-timeline')).toContainText('签发')
  await page.getByTestId('toggle-code').click()
  await expect(page.getByTestId('license-code')).not.toContainText('点击展开')
  await expect(page.getByTestId('license-drawer').getByTestId('act-suspend')).toBeDisabled()
  await expect(page.getByTestId('license-drawer').getByTestId('act-resume')).toBeDisabled()
  await expect(page.getByTestId('license-drawer').getByTestId('act-extend')).toBeEnabled()
  await page.screenshot({ path: path.join(SHOTS, '04-license-drawer.png') })
})

test('激活后停用 -> suspended；吊销需输入 lid；之后所有按钮禁用', async ({ page, request }) => {
  const r = await request.post(`${API}/e2e/activate/${lid}`)
  expect(r.ok()).toBeTruthy()

  await login(page, 'e2e_super')
  await page.getByTestId('lid-' + lid).click()
  await expect(page.getByTestId('license-drawer').getByTestId('act-suspend')).toBeEnabled()

  await page.getByTestId('license-drawer').getByTestId('act-suspend').click()
  await page.getByTestId('confirm-ok').click()
  const row = page.locator('.el-table__body-wrapper tr', { hasText: lid })
  await expect(row.locator('.status-tag')).toHaveAttribute('data-status', 'suspended')
  await expect(page.getByTestId('license-drawer').getByTestId('act-resume')).toBeEnabled()
  await expect(page.getByTestId('license-drawer').getByTestId('act-suspend')).toBeDisabled()

  await page.getByTestId('license-drawer').getByTestId('act-revoke').click()
  await expect(page.getByTestId('confirm-ok')).toBeDisabled()
  await field(page, 'confirm-input').fill(lid)
  await page.getByTestId('confirm-ok').click()
  await expect(row.locator('.status-tag')).toHaveAttribute('data-status', 'revoked')
  for (const a of ['extend', 'suspend', 'resume', 'revoke']) await expect(page.getByTestId('license-drawer').getByTestId('act-' + a)).toBeDisabled()
  await expect(page.getByTestId('event-timeline')).toContainText('吊销')
})

test('super：管理员管理密码少于 12 位前端拦截；审计日志有记录', async ({ page }) => {
  await login(page, 'e2e_super')
  await page.getByTestId('menu-admins').click()
  await page.getByTestId('open-create-admin').click()
  await field(page, 'admin-username').fill('newop')
  await field(page, 'admin-password').fill('short')
  await page.getByTestId('admin-create-ok').click()
  await expect(page.locator('.el-form-item__error')).toContainText('至少 12 位')
  await page.keyboard.press('Escape')

  // 最后一个 super 不能被禁用（自己的行按钮被禁用，这里改用审计确认前面的操作）
  await page.getByTestId('menu-audit').click()
  await expect(page.locator('.el-table__body-wrapper .el-table__body').first()).toContainText('吊销授权')
  await expect(page.locator('.el-table__body-wrapper .el-table__body').first()).toContainText('签发授权')
})

test('ops：看不到管理员管理菜单，也进不去；有操作按钮', async ({ page }) => {
  await login(page, 'e2e_ops')
  await expect(page.getByTestId('menu-licenses')).toBeVisible()
  await expect(page.getByTestId('menu-audit')).toBeVisible()
  await expect(page.getByTestId('menu-admins')).toHaveCount(0)
  await expect(page.getByTestId('open-issue')).toBeVisible()
  await page.goto('/admins')
  await expect(page).toHaveURL(/\/licenses/)
})

test('readonly：只能看，没有签发和任何操作按钮；审计、管理员菜单不可见', async ({ page }) => {
  await login(page, 'e2e_readonly')
  await expect(page.locator('.el-table__body-wrapper .el-table__body').first()).toContainText(lid)
  await expect(page.getByTestId('open-issue')).toHaveCount(0)
  await expect(page.locator('[data-testid^="act-"]')).toHaveCount(0)
  await expect(page.getByTestId('menu-audit')).toHaveCount(0)
  await expect(page.getByTestId('menu-admins')).toHaveCount(0)
  await page.getByTestId('lid-' + lid).click()
  await expect(page.getByTestId('license-drawer')).toContainText(lid)
  await expect(page.locator('[data-testid^="act-"]')).toHaveCount(0)
})

test('退出登录回到登录页，返回键不能回到受保护页面', async ({ page }) => {
  await login(page, 'e2e_super')
  await page.getByTestId('logout').click()
  await expect(page).toHaveURL(/\/login/)
  await page.goto('/licenses')
  await expect(page).toHaveURL(/\/login/)
})
