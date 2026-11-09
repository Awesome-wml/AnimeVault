// 真实模型冒烟（E2E_REAL=1 scripts/e2e.sh）：真智谱跑 小说（AI 写） → 一键提取（资产 + 分镜）
// 密钥从 E2E_ZHIPU_KEY_FILE 读，经接口写进测试库里这个测试用户的全局密钥；不进截图、不进日志，跑完随测试库删除。
const fs = require('fs')
const path = require('path')
const { test, expect } = require('@playwright/test')
const { snap, expectToast, nav, registerViaUi, createProject, reportDir } = require('./helpers')

const MINUTES = 60 * 1000
const timings = {}

async function timed(name, fn) {
  const t0 = Date.now()
  try {
    return await fn()
  } finally {
    timings[name] = Math.round((Date.now() - t0) / 1000)
    console.log(`[耗时] ${name}: ${timings[name]}s`)
  }
}

/** 等成功提示；先出现错误提示就立刻失败（不干等到超时） */
async function waitOk(page, text, timeout = 10 * MINUTES) {
  const ok = page.locator('.el-message').filter({ hasText: text }).first()
  const err = page.locator('.el-message--error').first()
  await expect(ok.or(err)).toBeVisible({ timeout })
  if (await err.isVisible()) throw new Error(`页面报错：${await err.textContent()}`)
}

test.describe.serial('真实模型冒烟', () => {
  let page

  test.beforeAll(async ({ browser }) => {
    page = await browser.newPage()
  })

  test.afterAll(async () => {
    fs.mkdirSync(reportDir, { recursive: true })
    fs.writeFileSync(path.join(reportDir, 'real-timings.json'), JSON.stringify(timings, null, 2))
    await page.close()
  })

  test('准备：注册并写入真实模型密钥', async ({}, testInfo) => {
    const keyFile = process.env.E2E_ZHIPU_KEY_FILE
    expect(keyFile && fs.existsSync(keyFile), '需要 E2E_ZHIPU_KEY_FILE').toBeTruthy()
    await registerViaUi(page, 'real')
    const token = await page.evaluate(() => localStorage.getItem('token'))
    const res = await page.request.put('/api/auth/config', {
      headers: { Authorization: `Bearer ${token}` },
      data: { doubao_api_key: fs.readFileSync(keyFile, 'utf8').trim(), doubao_model: 'glm-4.5-flash' }
    })
    expect(res.status()).toBe(200)
    await createProject(page, '真实冒烟')
    await snap(page, testInfo, 'ready')
  })

  test('小说：AI 写一篇（真实流式）', async ({}, testInfo) => {
    await page.getByText('AI 写一篇小说').click()
    await page.getByLabel('故事梗概').fill('外门弟子林风在暴雨演武场被师兄赵虎羞辱，祖传古戒觉醒，他立下三月后族比之约')
    await page.getByLabel('主角设定').fill('林风，十七岁，隐忍坚韧；赵虎，二十岁，跋扈；苏婉，十八岁，温柔')
    const words = page.getByLabel('目标字数')
    await words.fill('1000')
    await words.blur()
    await timed('AI 写小说', async () => {
      await page.getByRole('button', { name: '开始生成' }).click()
      await waitOk(page, '小说生成完成')
    })
    const text = await page.getByLabel('小说内容').inputValue()
    // 冒烟只要求真的写出了正文；字数是否达到目标由提示词质量决定，记在报告里
    console.log(`[结果] AI 写小说 ${text.length} 字（目标 1000）`)
    expect(text.length).toBeGreaterThan(100)
    await page.getByRole('button', { name: '保存', exact: true }).click()
    await expectToast(page, '已保存')
    testInfo.annotations.push({ type: '小说字数', description: String(text.length) })
    await snap(page, testInfo, 'novel')
  })

  test('一键提取：真实资产提取 + 拆分镜', async ({}, testInfo) => {
    await page.getByRole('button', { name: '一键提取' }).click()
    // 资产提取完成后页面提示“正在拆分镜”，以此把两段耗时分开
    await timed('资产提取', () => waitOk(page, '正在拆分镜'))
    await timed('拆分镜', () => waitOk(page, '一键提取完成'))
    const count = async label => Number(await nav(page, label).locator('.side-nav__count').textContent())
    const chars = await count('角色')
    expect(chars).toBeGreaterThan(0)
    testInfo.annotations.push({ type: '提取结果', description: `角色 ${chars}、场景 ${await count('场景')}、道具 ${await count('道具')}` })
    await snap(page, testInfo, 'extracted')

    await nav(page, '分镜').click()
    const rows = page.getByRole('region', { name: '镜头列表' }).locator('.shot-row')
    await expect(rows.first()).toBeVisible()
    const n = await rows.count()
    testInfo.annotations.push({ type: '镜头数', description: String(n) })
    expect(n).toBeGreaterThan(0)
    await snap(page, testInfo, 'shots')
  })
})
