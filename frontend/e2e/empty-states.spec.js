// 空状态与失败状态：新作品还没有小说、资产、分镜、视频时各页的提示
const { test, expect } = require('@playwright/test')
const { snap, expectToast, nav, registerViaUi, createProject } = require('./helpers')

test.describe.serial('空状态', () => {
  let page

  test.beforeAll(async ({ browser }) => {
    page = await browser.newPage()
    await registerViaUi(page, 'empty')
    await createProject(page, '空作品')
  })

  test.afterAll(async () => {
    await page.close()
  })

  test('角色 / 场景 / 道具页为空时的引导', async ({}, testInfo) => {
    for (const label of ['角色', '场景', '道具']) {
      await nav(page, label).click()
      await expect(page.getByRole('heading', { name: `还没有${label}` })).toBeVisible()
    }
    await snap(page, testInfo, 'empty-props')
  })

  test('AI 提取对话框：没有文本时提示', async ({}, testInfo) => {
    await nav(page, '角色').click()
    await page.getByRole('button', { name: 'AI 提取角色' }).click()
    const dialog = page.getByRole('dialog', { name: 'AI 提取角色' })
    await dialog.getByRole('button', { name: '提取', exact: true }).click()
    await expectToast(page, '请先粘贴小说文本')
    await snap(page, testInfo, 'extract-dialog-empty')
    await dialog.getByRole('button', { name: '取消' }).click()
  })

  test('分镜页为空：提示去剧本页；拆分镜提示小说为空', async ({}, testInfo) => {
    await nav(page, '分镜').click()
    await expect(page.getByRole('heading', { name: '这一集还没有分镜' })).toBeVisible()
    await expect(page.getByRole('button', { name: '批量生成视频' })).toBeDisabled()
    await page.getByRole('button', { name: '拆分镜' }).click()
    await expectToast(page, '小说还是空的')
    await snap(page, testInfo, 'empty-shots')
    await page.getByRole('link', { name: '去剧本页' }).click()
    await expect(page.getByRole('heading', { name: '剧本', exact: true })).toBeVisible()
  })

  test('配音与成片页为空', async ({}, testInfo) => {
    await nav(page, '配音与字幕').click()
    await expect(page.getByText('这一集还没有分镜。先在剧本页一键提取')).toBeVisible()
    await expect(page.getByRole('button', { name: '生成全部配音' })).toBeDisabled()
    await page.getByRole('button', { name: '下载字幕 SRT' }).click()
    await expectToast(page, '该项目没有分镜数据')
    await nav(page, '成片').click()
    await expect(page.getByText('这一集还没有生成好的视频')).toBeVisible()
    await page.getByRole('button', { name: '导出到剪映' }).click()
    await expectToast(page, '没有已生成的视频')
    await snap(page, testInfo, 'empty-final')
  })
})
