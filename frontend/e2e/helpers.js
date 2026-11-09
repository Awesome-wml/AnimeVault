// 端到端测试公共方法：截图、轻提示、确认框、注册
const fs = require('fs')
const path = require('path')
const { expect } = require('@playwright/test')

const reportDir = process.env.E2E_REPORT_DIR || path.join(__dirname, '..', 'e2e-report')
const shotDir = path.join(reportDir, 'screenshots')
const shotNo = {}

/** 每步截图：存到 <报告目录>/screenshots/<用例文件>-NN-名称.png，同时挂到 HTML 报告 */
async function snap(page, testInfo, name) {
  fs.mkdirSync(shotDir, { recursive: true })
  const spec = path.basename(testInfo.file).replace(/\.spec\.js$/, '')
  shotNo[spec] = (shotNo[spec] || 0) + 1
  const file = path.join(shotDir, `${spec}-${String(shotNo[spec]).padStart(2, '0')}-${name}.png`)
  await page.screenshot({ path: file, fullPage: true })
  await testInfo.attach(name, { path: file, contentType: 'image/png' })
  return file
}

/** Element UI 轻提示（$message）出现指定文字 */
async function expectToast(page, text, timeout) {
  const toast = page.locator('.el-message').filter({ hasText: text }).first()
  await expect(toast).toBeVisible(timeout ? { timeout } : undefined)
  return toast
}

/** 等所有轻提示消失，避免下一步误读到上一步的提示 */
async function clearToasts(page) {
  const all = page.locator('.el-message')
  for (const el of await all.all()) {
    await el.locator('.el-message__closeBtn').click({ timeout: 500 }).catch(() => {})
  }
  await expect(all).toHaveCount(0, { timeout: 10000 })
}

/** MessageBox 确认/输入框：点指定按钮 */
async function answerBox(page, buttonText, inputValue) {
  const box = page.locator('.el-message-box').last()
  await expect(box).toBeVisible()
  if (inputValue !== undefined) await box.locator('input').fill(inputValue)
  await box.getByRole('button', { name: buttonText }).click()
  await expect(box).toBeHidden()
}

/** 侧栏菜单 */
function nav(page, label) {
  return page.locator('.side-nav__item').filter({ has: page.locator('.side-nav__label', { hasText: new RegExp(`^${label}$`) }) })
}

/** 从浏览器注册新用户，返回用户名 */
async function registerViaUi(page, prefix = 'e2e') {
  const username = `${prefix}_${Date.now().toString(16)}`
  await page.goto('/#/register')
  await page.getByLabel('用户名').fill(username)
  await page.getByLabel('密码', { exact: true }).fill('e2e-pass-123')
  await page.getByLabel('确认密码').fill('e2e-pass-123')
  await page.getByRole('button', { name: '注册并开始' }).click()
  await expect(page).toHaveURL(/#\/home$/)
  return username
}

/** 新建作品并进入小说页，返回作品 id */
async function createProject(page, name) {
  await page.getByRole('button', { name: '新建作品' }).first().click()
  const dialog = page.getByRole('dialog', { name: '新建作品' })
  await dialog.getByLabel('作品名').fill(name)
  await dialog.getByRole('button', { name: '创建并开始' }).click()
  await expect(page).toHaveURL(/#\/projects\/[0-9a-f]{24}\/novel/)
  return page.url().match(/projects\/([0-9a-f]{24})/)[1]
}

module.exports = { snap, expectToast, clearToasts, answerBox, nav, registerViaUi, createProject, reportDir }
