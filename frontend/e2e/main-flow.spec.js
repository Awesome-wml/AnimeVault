// 主流程（替身模式）：注册 → 新建作品 → 小说 → 一键提取 → 风格 → 资产出图 → 分镜 → 视频 → 配音与字幕 → 成片 → 管理剧集
// 各步共享同一个浏览器页面，按顺序执行。
const { test, expect } = require('@playwright/test')
const { snap, expectToast, clearToasts, answerBox, nav, registerViaUi, createProject } = require('./helpers')

const NOVEL = `暴雨压在林家演武场上。林风攥着扫帚站在场边。
赵虎踩着积水走过来，冷笑一声：“你也配站在这里？”
林风左手的青铜古戒忽然发烫。苏婉撑着油纸伞站在廊下。`

test.describe.serial('主流程', () => {
  let page
  let pid

  test.beforeAll(async ({ browser }) => {
    page = await browser.newPage()
  })

  test.afterAll(async () => {
    await page.close()
  })

  test('01 从浏览器注册新用户', async ({}, testInfo) => {
    await registerViaUi(page)
    await expect(page.getByRole('heading', { name: '开始第一部作品' })).toBeVisible()
    await expect(page.getByText('还没有作品')).toBeVisible()
    await snap(page, testInfo, 'home-empty')
  })

  test('02 新建作品进入小说页', async ({}, testInfo) => {
    pid = await createProject(page, '暴雨演武场')
    await expect(page.getByRole('heading', { name: '小说' })).toBeVisible()
    await expect(page.locator('.side-nav__name')).toHaveText('暴雨演武场')
    await snap(page, testInfo, 'novel-empty')
  })

  test('03 空状态：没有小说时点一键提取给出提示', async ({}, testInfo) => {
    await page.getByRole('button', { name: '一键提取' }).click()
    await expectToast(page, '请先贴入小说内容')
    await snap(page, testInfo, 'extract-without-novel')
    await clearToasts(page)
  })

  test('04 粘贴小说并保存', async ({}, testInfo) => {
    await page.getByLabel('小说内容').fill(NOVEL)
    await expect(page.getByText('有未保存的修改')).toBeVisible()
    await page.getByRole('button', { name: '保存', exact: true }).click()
    await expectToast(page, '已保存')
    await expect(page.locator('.page-header__subtitle')).toContainText('已保存')
    await snap(page, testInfo, 'novel-pasted')
    await clearToasts(page)
  })

  test('05 失败状态：未配置模型密钥时一键提取报错', async ({}, testInfo) => {
    await page.getByRole('button', { name: '一键提取' }).click()
    await expectToast(page, '请先配置 API 密钥')
    await expect(page.getByRole('button', { name: '一键提取' })).toBeEnabled()
    await snap(page, testInfo, 'extract-without-key')
    await clearToasts(page)
  })

  test('06 设置全局模型密钥', async ({}, testInfo) => {
    await page.locator('.project-layout__settings').click()
    await expect(page).toHaveURL(/#\/settings\/models/)
    // 对话框打开后会异步读取当前配置，读完再填，避免被回填的空值覆盖
    const loaded = page.waitForResponse(r => r.url().includes('/api/auth/config') && r.request().method() === 'GET')
    await page.getByRole('button', { name: '全局密钥' }).click()
    await loaded
    const dialog = page.getByRole('dialog', { name: '全局密钥' })
    await expect(dialog.getByText('还没有配置全局密钥')).toBeVisible()
    // 替身模式下密钥不会发往外部
    await dialog.getByLabel('API 密钥').fill('e2e-fake-key')
    await snap(page, testInfo, 'global-key')
    await dialog.getByRole('button', { name: '保存' }).click()
    await expectToast(page, '已保存')
    await clearToasts(page)
  })

  test('07 AI 写小说（流式写入正文）并保存', async ({}, testInfo) => {
    await page.goto(`/#/projects/${pid}/novel`)
    await expect(page.getByLabel('小说内容')).toHaveValue(NOVEL)
    await page.getByText('AI 写一篇小说').click()
    await page.getByLabel('故事梗概').fill('少年在家族演武场受辱，古戒觉醒后立下族比之约')
    await page.getByLabel('主角设定').fill('林风，十七岁，隐忍坚韧')
    await page.getByRole('button', { name: '开始生成' }).click()
    await expectToast(page, '小说生成完成')
    await expect(page.getByLabel('小说内容')).toHaveValue(/^暴雨演武场\n\n暴雨压在林家演武场上/)
    await page.getByRole('button', { name: '保存', exact: true }).click()
    await expectToast(page, '已保存')
    await snap(page, testInfo, 'novel-ai-written')
    await clearToasts(page)
  })

  test('08 一键提取角色、场景、道具并拆分镜', async ({}, testInfo) => {
    await page.getByRole('button', { name: '一键提取' }).click()
    await expectToast(page, '一键提取完成')
    await expect(nav(page, '角色').locator('.side-nav__count')).toHaveText('3')
    await expect(nav(page, '场景').locator('.side-nav__count')).toHaveText('1')
    await expect(nav(page, '道具').locator('.side-nav__count')).toHaveText('1')
    await snap(page, testInfo, 'extracted')
    await clearToasts(page)
  })

  test('09 选择风格并保存', async ({}, testInfo) => {
    await nav(page, '风格').click()
    await expect(page.getByRole('heading', { name: '风格' })).toBeVisible()
    const card = page.getByRole('radiogroup', { name: '题材风格' }).getByRole('button', { name: /仙侠/ })
    await card.click()
    await expect(card).toHaveAttribute('aria-pressed', 'true')
    await expect(page.getByText('仙侠：御剑飞行')).toBeVisible()
    await page.getByRole('button', { name: '保存' }).click()
    await expectToast(page, '风格已保存')
    await snap(page, testInfo, 'style')
    await clearToasts(page)
  })

  test('10 角色：生成三视图、自动配音色', async ({}, testInfo) => {
    await nav(page, '角色').click()
    await expect(page.locator('.page-header__subtitle')).toHaveText('3 个角色')
    const card = page.locator('.asset-card').filter({ hasText: '林风' })
    await expect(card).toContainText('主要角色')
    await card.getByRole('button', { name: '生成三视图', exact: true }).click()
    await expectToast(page, '林风 的三视图已生成')
    await expect(card.locator('img')).toBeVisible()
    await expect(card).toContainText('已有三视图')
    await page.getByRole('button', { name: 'AI 自动配音色' }).click()
    await expectToast(page, '个主要角色匹配音色')
    await snap(page, testInfo, 'characters')
    await clearToasts(page)
  })

  test('11 场景、道具：生成参考图', async ({}, testInfo) => {
    for (const [label, name] of [['场景', '暴雨萧瑟演武场'], ['道具', '青铜古戒']]) {
      await nav(page, label).click()
      const card = page.locator('.asset-card').filter({ hasText: name })
      await card.getByRole('button', { name: '生成参考图', exact: true }).click()
      await expectToast(page, `${name} 的参考图已生成`)
      await expect(card.locator('img')).toBeVisible()
      await snap(page, testInfo, label === '场景' ? 'scenes' : 'props')
      await clearToasts(page)
    }
  })

  test('12 分镜：查看、编辑台词、生成画面、再拆一次分镜', async ({}, testInfo) => {
    await nav(page, '分镜').click()
    const rows = page.getByRole('region', { name: '镜头列表' }).locator('.shot-row')
    await expect(rows).toHaveCount(3)
    await expect(rows.nth(1)).toContainText('你也配站在这里？')
    await expect(page.locator('.page-header__subtitle')).toContainText('3 个镜头')

    await rows.nth(1).click()
    const detail = page.getByRole('region', { name: '镜头 2 详情' })
    await expect(detail.getByLabel('说话人')).toHaveValue('赵虎')
    await detail.getByLabel('台词').fill('你也配站在这里？滚出去！')
    await detail.getByLabel('台词').blur()
    await expect(rows.nth(1)).toContainText('滚出去')

    await detail.getByRole('button', { name: '生成画面' }).click()
    await expectToast(page, '画面已生成')
    // 详情顶部的画面框（MediaFrame）换成生成的图
    await expect(detail.getByTestId('media-frame').first().locator('img')).toBeVisible()
    await snap(page, testInfo, 'shots')
    await clearToasts(page)

    await page.getByRole('button', { name: '拆分镜' }).click()
    await answerBox(page, '开始拆分')
    await expectToast(page, '拆分镜完成：3 个镜头')
    await expect(rows).toHaveCount(6)
    // 追加的镜头镜号接着往下编
    await expect(rows.locator('.shot-row__no')).toHaveText(['1', '2', '3', '4', '5', '6'])
    await clearToasts(page)
  })

  test('13 视频：单条生成、批量生成', async ({}, testInfo) => {
    const rows = page.getByRole('region', { name: '镜头列表' }).locator('.shot-row')
    await rows.nth(0).click()
    const detail = page.getByRole('region', { name: '镜头 1 详情' })
    await detail.getByRole('button', { name: '生成视频' }).click()
    await answerBox(page, '生成')
    await expectToast(page, '分镜 1 生成成功')
    await expect(detail.getByTestId('media-frame').first().locator('video')).toBeVisible()
    await expect(rows.nth(0)).toContainText('已出视频')
    await clearToasts(page)

    await page.getByRole('button', { name: '批量生成视频' }).click()
    const dialog = page.getByRole('dialog', { name: '批量生成视频' })
    await expect(dialog).toContainText('共 6 个镜头，已出视频 1 个，待生成 5 个')
    await expect(dialog.getByRole('cell', { name: '替身账号1' })).toBeVisible()
    await snap(page, testInfo, 'batch-dialog')
    await dialog.getByRole('button', { name: '开始生成' }).click()
    const result = page.locator('.el-message-box').filter({ hasText: '生成结果' })
    await expect(result.locator('p')).toHaveText(['共 5 条：成功 5，失败 0', '替身账号1：成功 5，失败 0'])
    // SSE 进度推送：每条完成都有提示
    await expectToast(page, '生成完成')
    await result.getByRole('button', { name: '知道了' }).click()
    await expect(page.locator('.page-header__subtitle')).toContainText('已出视频 6 个')
    await snap(page, testInfo, 'videos')
    await clearToasts(page)
  })

  test('14 配音与字幕：自动配音色、生成全部配音、试听、下载字幕', async ({}, testInfo) => {
    await nav(page, '配音与字幕').click()
    const table = page.locator('.el-table')
    await expect(table.locator('tbody tr')).toHaveCount(6)
    await page.getByRole('button', { name: '自动配音色' }).click()
    await expectToast(page, '个主要角色匹配音色')
    await clearToasts(page)

    await page.getByRole('button', { name: '生成全部配音' }).click()
    await expectToast(page, '全部 6 条配音完成')
    await expect(table.getByRole('button', { name: '试听' })).toHaveCount(6)
    await expect(table.getByText('已配音')).toHaveCount(6)
    await snap(page, testInfo, 'voice')
    await clearToasts(page)

    const srt = page.context().waitForEvent('response', r => r.url().includes('/api/tts/srt/download/'))
    await page.getByRole('button', { name: '下载字幕 SRT' }).click()
    const res = await srt
    expect(res.status()).toBe(200)
    expect(res.headers()['content-disposition'] || '').toContain('.srt')
    await expectToast(page, 'SRT字幕生成成功')
    await clearToasts(page)
  })

  test('15 成片：连续预览、导出剪映、下载字幕', async ({}, testInfo) => {
    await nav(page, '成片').click()
    await expect(page.locator('.page-header__subtitle')).toContainText('已有 6 / 6 个镜头的视频')
    await expect(page.getByText('所有镜头都有视频了')).toBeVisible()
    await expect(page.locator('video').first()).toBeVisible()
    await page.getByRole('button', { name: '导出到剪映' }).click()
    await expectToast(page, '已导出6个视频到剪映草稿')
    await snap(page, testInfo, 'final')
    await clearToasts(page)

    const srt = page.context().waitForEvent('response', r => r.url().includes('/api/tts/srt/download/'))
    await page.getByRole('button', { name: '下载字幕' }).click()
    expect((await srt).status()).toBe(200)
    await clearToasts(page)
  })

  test('16 管理剧集：新建、进入、重命名、导出、删除', async ({}, testInfo) => {
    await nav(page, '管理剧集').click()
    const table = page.locator('.el-table')
    await expect(table.locator('.el-table__empty-text')).toHaveText(/还没有剧集/)
    await page.getByRole('button', { name: '新建一集' }).click()
    await answerBox(page, '确定')
    await expectToast(page, '已创建')
    // 第一集接收建集前拆出的 6 个分镜（含已出视频数）
    const row = table.locator('.el-table__row').filter({ hasText: '第 1 集' })
    await expect(row.locator('td').nth(1)).toHaveText('6')
    await expect(row.locator('td').nth(2)).toHaveText('6')
    await clearToasts(page)

    await row.getByRole('link', { name: '进入' }).click()
    await expect(page).toHaveURL(/shots\?ep=/)
    await expect(page.getByRole('region', { name: '镜头列表' }).locator('.shot-row')).toHaveCount(6)
    await expect(page.locator('.page-header__subtitle')).toContainText('第 1 集')

    await nav(page, '管理剧集').click()
    await row.getByRole('button', { name: '重命名' }).click()
    await answerBox(page, '确定', '第一集 · 暴雨')
    await expectToast(page, '已重命名')
    const renamed = table.locator('.el-table__row').filter({ hasText: '第一集 · 暴雨' })
    await expect(renamed).toBeVisible()
    await clearToasts(page)

    await renamed.getByRole('button', { name: '导出剪映' }).click()
    await expectToast(page, '已导出6个视频到剪映草稿')
    await clearToasts(page)

    // 再建一集并删除（删除会连同该集分镜一起删掉）
    await page.getByRole('button', { name: '新建一集' }).click()
    await answerBox(page, '确定')
    const second = table.locator('.el-table__row').filter({ hasText: '第 2 集' })
    await expect(second.locator('td').nth(1)).toHaveText('0')
    await snap(page, testInfo, 'episodes')
    await clearToasts(page)
    await second.getByRole('button', { name: '删除' }).click()
    await answerBox(page, '删除')
    await expectToast(page, '已删除')
    await expect(second).toHaveCount(0)
    await expect(renamed).toBeVisible()
  })

  test('17 首页显示接着做这部作品', async ({}, testInfo) => {
    await page.goto('/#/home')
    await expect(page.getByRole('heading', { name: '接着做《暴雨演武场》' })).toBeVisible()
    await expect(page.locator('.page-header__subtitle')).toContainText('1 集，共 6 个镜头，6 个已出视频')
    await snap(page, testInfo, 'home-continue')
  })
})
