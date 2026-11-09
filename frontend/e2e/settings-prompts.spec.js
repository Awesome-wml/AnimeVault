// 设置 - 提示词：内置提示词可看、可改、可复制为自定义、可恢复；自定义默认标出“正在覆盖内置”
const { test, expect } = require('@playwright/test')
const { snap, expectToast, clearToasts, answerBox, registerViaUi } = require('./helpers')

const BUILTIN_COUNT = 13

test.describe.serial('提示词设置页', () => {
  let page

  test.beforeAll(async ({ browser }) => {
    page = await browser.newPage()
    await registerViaUi(page, 'prompts')
    await page.goto('/#/settings/prompts')
    await expect(page.getByRole('heading', { name: '提示词' })).toBeVisible()
  })

  test.afterAll(async () => {
    await page.close()
  })

  const rows = () => page.locator('.el-table__row')
  const builtinRow = (type) => page.locator('.el-table__row', { has: page.getByTestId('builtin-tag') }).filter({ hasText: type })

  test('01 列表：13 条内置到位，没有视频类型', async ({}, testInfo) => {
    await expect(page.getByTestId('builtin-tag')).toHaveCount(BUILTIN_COUNT)
    await expect(page.locator('.chip', { hasText: '视频' })).toHaveCount(0)
    await expect(page.locator('.page-header__subtitle')).toContainText('视频提示词由系统')
    // 按类型筛选只剩该类型
    await page.locator('.chip', { hasText: /^小说$/ }).click()
    await expect(rows()).toHaveCount(1)
    await expect(rows().first()).toContainText('内置·生成小说')
    await snap(page, testInfo, 'prompts-list')
  })

  test('02 内置：查看/编辑只能改内容，改后可恢复内置', async ({}, testInfo) => {
    const row = builtinRow('内置·生成小说')
    await expect(row.getByRole('button', { name: '删除' })).toHaveCount(0)
    await row.getByRole('button', { name: '查看/编辑' }).click()
    const dialog = page.getByRole('dialog', { name: '查看 / 编辑内置提示词' })
    await expect(dialog.getByText('占位符')).toBeVisible()
    await expect(dialog.getByLabel('名称')).toBeDisabled()
    const content = dialog.getByLabel('提示词内容')
    const original = await content.inputValue()
    expect(original.length).toBeGreaterThan(200)
    await snap(page, testInfo, 'prompts-builtin-edit')
    await content.fill('我改过的小说模板 {genre}')
    await dialog.getByRole('button', { name: '保存' }).click()
    await expectToast(page, '已保存')
    await clearToasts(page)
    await expect(row).toContainText('我改过的小说模板')

    await row.getByRole('button', { name: '恢复内置' }).click()
    await answerBox(page, '恢复')
    await expectToast(page, '已恢复内置')
    await clearToasts(page)
    await expect(row).not.toContainText('我改过的小说模板')
    await expect(row).toContainText(original.slice(0, 20))
  })

  test('03 复制为自定义并设为默认：标出“正在覆盖内置（默认）”', async ({}, testInfo) => {
    await builtinRow('内置·生成小说').getByRole('button', { name: '复制为自定义' }).click()
    await expectToast(page, '已复制为自定义')
    await clearToasts(page)
    await expect(rows()).toHaveCount(2)
    const copy = page.locator('.el-table__row', { hasText: '内置·生成小说（副本）' })
    await expect(copy.getByTestId('builtin-tag')).toHaveCount(0)
    await copy.getByRole('button', { name: '设为默认' }).click()
    await expect(copy).toContainText('正在覆盖内置（默认）')
    await expect(copy.getByRole('button', { name: '设为默认' })).toHaveCount(0)
    await snap(page, testInfo, 'prompts-overriding')

    // 删掉自定义副本后不再覆盖
    await copy.getByRole('button', { name: '删除' }).click()
    await answerBox(page, '删除')
    await expectToast(page, '已删除')
    await clearToasts(page)
    await expect(rows()).toHaveCount(1)
  })
})
