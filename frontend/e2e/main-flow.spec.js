// 主流程（替身模式）：注册 → 新建作品 → 小说 → 一键提取 → 风格 → 资产出图 → 分镜 → 视频 → 配音与字幕 → 成片 → 管理剧集
// 各步共享同一个浏览器页面，按顺序执行。
const { test, expect } = require('@playwright/test')
const { snap, expectToast, clearToasts, answerBox, nav, registerViaUi, createProject } = require('./helpers')

/** 给某类请求加延迟（看得到进度、来得及取消）；fail(n) 返回 true 时让第 n 个请求失败。返回已发出的请求数 */
async function slowRoute(page, pattern, { delay = 600, fail } = {}) {
  const count = { n: 0 }
  await page.route(pattern, async route => {
    const n = ++count.n
    await new Promise(r => setTimeout(r, delay))
    if (fail && fail(n)) {
      await route.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({ detail: '替身：模拟限流' }) })
    } else {
      await route.continue().catch(() => {})
    }
  })
  return count
}

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
    // 进度区停在失败阶段并显示原因
    await expect(page.getByRole('status', { name: '提取进度' })).toContainText('资产提取失败：请先配置 API 密钥')
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
    // 分阶段进度：资产 → 拆分镜，完成后留下结果
    await expect(page.getByRole('status', { name: '提取进度' })).toContainText('一键提取完成：已生成角色、道具、场景；拆分镜完成：3 段')
    await expect(nav(page, '角色').locator('.side-nav__count')).toHaveText('3')
    await expect(nav(page, '场景').locator('.side-nav__count')).toHaveText('1')
    await expect(nav(page, '道具').locator('.side-nav__count')).toHaveText('1')
    await snap(page, testInfo, 'extracted')
    await clearToasts(page)
  })

  test('09 选择风格并保存', async ({}, testInfo) => {
    await nav(page, '风格').click()
    await expect(page.getByRole('heading', { name: '风格' })).toBeVisible()
    // 两步：第一行选媒介（2D 动漫再选子画风），第二行选题材
    const medium = page.getByRole('radiogroup', { name: '媒介' }).getByRole('button', { name: /2D 动漫/ })
    await medium.click()
    await expect(medium).toHaveAttribute('aria-pressed', 'true')
    const subStyles = page.getByRole('radiogroup', { name: '2D 画风' }).getByRole('radio')
    await expect(subStyles).toHaveCount(3)
    await subStyles.filter({ hasText: '古风厚涂' }).click()
    const card = page.getByRole('radiogroup', { name: '题材' }).getByRole('button', { name: /仙侠/ })
    await card.click()
    await expect(card).toHaveAttribute('aria-pressed', 'true')
    await expect(page.getByText('古风厚涂 · 仙侠：御剑飞行')).toBeVisible()
    // 视频模型：4 个可选，默认 Seedance 2.0 Fast；选 2 倍消耗的会提示，再换回 Fast
    const models = page.getByRole('radiogroup', { name: '视频模型' }).getByRole('radio')
    await expect(models).toHaveCount(4)
    await expect(models.filter({ hasText: 'Seedance 2.0 Fast' })).toHaveAttribute('aria-checked', 'true')
    await models.filter({ hasText: '2 倍消耗' }).click()
    await expect(page.getByText('该模型每次生成消耗 2 倍额度')).toBeVisible()
    await models.filter({ hasText: 'Seedance 2.0 Fast' }).click()
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
    // 形态标签行：林风两个形态（形态名 · 出现场次）+ 音色描述；苏婉是旧格式数据，显示“单形态”
    const tags = card.getByRole('tab')
    await expect(tags).toHaveText(['场边扫地形态 · 第 1 场', '雨中立威形态 · 第 2 场'])
    await expect(tags.nth(0)).toHaveAttribute('aria-pressed', 'true')
    await expect(card).toContainText('17岁男性，清亮')
    await expect(page.locator('.asset-card').filter({ hasText: '苏婉' })).toContainText('单形态')
    await card.getByRole('button', { name: '生成三视图', exact: true }).click()
    await expectToast(page, '林风 的三视图已生成')
    await expect(card.locator('img')).toBeVisible()
    await expect(card).toContainText('已有三视图')
    await clearToasts(page)
    // 点第二个形态标签：切到该形态，它还没有图
    await tags.nth(1).click()
    await expect(tags.nth(1)).toHaveAttribute('aria-pressed', 'true')
    await expect(card.locator('img')).toHaveCount(0)
    await expect(card).toContainText('缺三视图')
    await snap(page, testInfo, 'character-form-switch')
    // 改当前形态的名称和场次
    await card.getByRole('button', { name: '编辑林风当前形态的名称和场次' }).click()
    await card.getByPlaceholder('形态名').fill('雨中立威')
    await card.getByPlaceholder('出现场次，如 1、3、5').fill('2、3')
    await card.getByRole('button', { name: '保存' }).click()
    await expectToast(page, '林风 的形态已更新')
    await expect(tags).toHaveText(['场边扫地形态 · 第 1 场', '雨中立威 · 第 2、3 场'])
    await clearToasts(page)
    await tags.nth(0).click()
    await expect(card.locator('img')).toBeVisible()
    await page.getByRole('button', { name: 'AI 自动配音色' }).click()
    await expectToast(page, '个主要角色匹配音色')
    await snap(page, testInfo, 'characters')
    await clearToasts(page)
  })

  test('10b 角色：一键生成全部三视图（只补缺图的形态）、全部重新生成、失败重试', async ({}, testInfo) => {
    const cards = page.locator('.asset-card')
    const progress = page.getByRole('status', { name: '批量生成三视图进度' })
    await expect(cards).toHaveCount(3)
    await expect(cards.locator('img')).toHaveCount(1)

    // 主按钮只处理还没有图的 3 张（林风第二形态、赵虎、苏婉）；每完成一张立即换上图
    await slowRoute(page, '**/api/assets/generate', { delay: 2000 })
    await page.getByRole('button', { name: '生成全部三视图' }).click()
    const busyBtn = page.locator('.page-header__actions .base-btn--primary')
    await expect(busyBtn).toContainText('正在生成 0 / 3')
    await expect(busyBtn).toBeDisabled()
    await expect(progress).toContainText('正在生成 1 / 3')
    await expect(cards.locator('img')).toHaveCount(2)
    await snap(page, testInfo, 'assets-batch-running')
    await expectToast(page, '全部 3 张三视图已生成')
    await expect(cards.locator('img')).toHaveCount(3)
    await expect(cards.filter({ hasText: '已有三视图' })).toHaveCount(3)
    await expect(progress).toHaveCount(0)
    await expect(page.getByRole('button', { name: '生成全部三视图' })).toBeEnabled()
    await snap(page, testInfo, 'assets-batch-done')
    await clearToasts(page)
    await page.unroute('**/api/assets/generate')

    // 都有图时主按钮给出提示
    await page.getByRole('button', { name: '生成全部三视图' }).click()
    await expectToast(page, '都已有三视图')
    await clearToasts(page)

    // 更多 → 全部重新生成（二次确认）；第 2 个请求失败，列出失败项后重试
    await slowRoute(page, '**/api/assets/generate', { delay: 100, fail: n => n === 2 })
    await page.getByRole('button', { name: '批量生成的更多操作' }).click()
    await page.locator('.el-dropdown-menu__item:visible', { hasText: '全部重新生成三视图' }).click()
    await answerBox(page, '重新生成')
    await expect(progress).toContainText('三视图已生成，1 张失败')
    await expect(progress.locator('li')).toHaveCount(1)
    await expect(progress.locator('li')).toContainText('替身：模拟限流')
    await snap(page, testInfo, 'assets-batch-failed')
    await clearToasts(page)
    await progress.getByRole('button', { name: '重试失败项' }).click()
    await expectToast(page, '全部 1 张三视图已生成')
    await expect(progress).toHaveCount(0)
    await expect(cards.locator('img')).toHaveCount(3)
    await page.unroute('**/api/assets/generate')
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
    // 按段显示：时长、填充率、逐句台词（说话人 + 类型）
    await expect(rows.nth(1)).toContainText('你也配站在这里？')
    await expect(rows.nth(1)).toContainText('15 秒 · 4 句')
    await expect(rows.nth(1)).toContainText('赵虎 · 对白')
    await expect(rows.nth(1)).toContainText(/填充 \d+%/)
    await expect(page.locator('.page-header__subtitle')).toContainText('3 段（每段一次视频生成）')

    await rows.nth(1).click()
    const detail = page.getByRole('region', { name: '第 2 段详情' })
    await expect(detail.getByLabel('段内小镜头')).toContainText('0–2.2 秒')  // 小镜头起止由台词时间推出（T-204 模型不再写）
    await expect(detail.getByLabel('第 1 句说话人')).toHaveValue('赵虎')
    await expect(detail.getByLabel('第 3 句类型')).toHaveValue('心声')
    await expect(detail.getByLabel('段内小镜头')).toContainText('［冷笑］')  // 小镜头的表情字段（T-211）
    await expect(detail.locator('.shot-detail__prompt')).toContainText('【整体设定】画面人物：赵虎')  // 名字后带【@图片N】
    await expect(detail.locator('.shot-detail__prompt')).toContainText('光影：冷白顶光')
    await expect(detail.locator('.shot-detail__prompt')).toContainText('情绪基调：紧张')
    await expect(detail.locator('.shot-detail__prompt')).toContainText('【硬性参数】段号 SEG002')
    await expect(detail.locator('.shot-detail__prompt')).toContainText('赵虎冷笑说：你也配站在这里？')
    await detail.getByLabel('第 1 句台词').fill('你也配站在这里？滚出去！')
    await detail.getByLabel('第 1 句台词').blur()
    await expect(rows.nth(1)).toContainText('滚出去')

    // 视频段的“生成画面”出 2×2 四格分镜图（T-215），下方列出 S1–S4 对应的时间段
    const board = detail.getByRole('region', { name: '四格分镜' })
    await expect(board).toContainText('还没有四格分镜')
    await expect(board.getByLabel('四格对应的时间段')).toContainText('S1 · 左上')
    await detail.getByRole('button', { name: '生成画面' }).click()
    await expectToast(page, '画面已生成')
    await expect(board.locator('img')).toBeVisible()
    await expect(detail.locator('.shot-detail__prompt')).toContainText('本段四格分镜（左上→右上→左下→右下')
    await expect(detail.locator('.shot-detail__prompt')).toContainText('S1 左上格]')
    await snap(page, testInfo, 'shots')
    await clearToasts(page)

    await page.getByRole('button', { name: '拆分镜' }).click()
    await answerBox(page, '开始拆分')
    await expectToast(page, '拆分镜完成：3 段，每段一次视频生成')
    await expect(rows).toHaveCount(6)
    // 追加的镜头镜号接着往下编
    await expect(rows.locator('.shot-row__no')).toHaveText(['1', '2', '3', '4', '5', '6'])
    await clearToasts(page)
  })

  test('12b 分镜：一键生成全部画面、取消、离开页面自动停止', async ({}, testInfo) => {
    const rows = page.getByRole('region', { name: '镜头列表' }).locator('.shot-row')
    const progress = page.getByRole('status', { name: '批量生成画面进度' })
    const allBtn = page.getByRole('button', { name: '生成全部画面' })
    await expect(rows).toHaveCount(6)
    await expect(rows.locator('img')).toHaveCount(1)
    // 次按钮（描边），实心主按钮仍只有“批量生成视频”
    await expect(allBtn).toHaveClass(/base-btn--secondary/)
    await expect(page.locator('.page-header__actions .base-btn--primary')).toHaveCount(1)
    await snap(page, testInfo, 'shots-batch-button')

    // 只处理还没有画面的 5 个，每完成一张缩略图立即出现
    await slowRoute(page, '**/api/image/generate', { delay: 300 })
    await allBtn.click()
    await expect(progress).toContainText(/正在生成 \d \/ 5/)
    await expect(page.locator('.page-header__actions').getByRole('button', { name: /正在生成/ })).toBeDisabled()
    await snap(page, testInfo, 'shots-batch-running')
    await expectToast(page, '全部 5 张画面已生成')
    await expect(rows.locator('img')).toHaveCount(6)
    await clearToasts(page)
    await page.unroute('**/api/image/generate')

    // 全部重新生成 → 取消：已在请求中的那张等它返回，后面的不再发
    const slow = await slowRoute(page, '**/api/image/generate', { delay: 1000 })
    await page.getByRole('button', { name: '生成画面的更多操作' }).click()
    await page.locator('.el-dropdown-menu__item:visible', { hasText: '全部重新生成画面' }).click()
    await answerBox(page, '重新生成')
    await expect(progress).toContainText('正在生成 0 / 6')
    await progress.getByRole('button', { name: '取消' }).click()
    await expectToast(page, '已取消：完成 1 张，剩余 5 张未处理')
    expect(slow.n).toBe(1)
    await clearToasts(page)

    // 再开一次后立刻离开页面：剩余不再请求
    slow.n = 0
    await page.getByRole('button', { name: '生成画面的更多操作' }).click()
    await page.locator('.el-dropdown-menu__item:visible', { hasText: '全部重新生成画面' }).click()
    await answerBox(page, '重新生成')
    await expect(progress).toBeVisible()
    await nav(page, '成片').click()
    await page.waitForTimeout(2500)
    expect(slow.n).toBe(1)
    await page.unroute('**/api/image/generate')
    await nav(page, '分镜').click()
    await expect(rows).toHaveCount(6)
    await expect(rows.locator('img')).toHaveCount(6)
    await clearToasts(page)
  })

  test('13 视频：单条生成、批量生成', async ({}, testInfo) => {
    const rows = page.getByRole('region', { name: '镜头列表' }).locator('.shot-row')
    await rows.nth(0).click()
    const detail = page.getByRole('region', { name: '第 1 段详情' })
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
    // 按句显示：两次拆分各 3 段、共 10 句 → 20 行；同一段的“段 / 状态 / 操作”合并成一格
    await expect(table.locator('tbody tr')).toHaveCount(20)
    await expect(table.locator('tbody tr').nth(3)).toContainText('赵虎 · 对白')
    await expect(table.getByRole('button', { name: '生成配音' })).toHaveCount(6)
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
