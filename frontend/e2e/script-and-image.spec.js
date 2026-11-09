// 剧本与出图模型（替身模式）：转剧本 → 场次编辑 → 基于剧本一键提取 → 设置文生图模型 → 资产出图选模型
const { test, expect } = require('@playwright/test')
const { snap, expectToast, clearToasts, answerBox, nav, registerViaUi, createProject } = require('./helpers')

const NOVEL = `暴雨压在林家演武场上。林风攥着扫帚站在场边。
赵虎踩着积水走过来，冷笑一声：“你也配站在这里？”
林风左手的青铜古戒忽然发烫。苏婉撑着油纸伞站在廊下。`

/** el-select：点开后选可见下拉里的某一项 */
async function choose(page, field, optionText) {
  await field.click()
  await page.locator('.el-select-dropdown__item:visible', { hasText: optionText }).first().click()
}

test.describe.serial('剧本与出图模型', () => {
  let page
  let pid

  test.beforeAll(async ({ browser }) => {
    page = await browser.newPage()
  })

  test.afterAll(async () => {
    await page.close()
  })

  test('01 准备：注册、新建作品、贴小说、配全局密钥', async () => {
    await registerViaUi(page, 'script')
    pid = await createProject(page, '剧本测试')
    // 等作品加载完（正文回填之后再输入，否则会被空正文覆盖）
    await expect(page.locator('.page-header__subtitle')).toContainText('已保存')
    await page.getByLabel('小说内容').fill(NOVEL)
    await page.getByRole('button', { name: '保存', exact: true }).click()
    await expectToast(page, '已保存')
    await clearToasts(page)

    await page.locator('.project-layout__settings').click()
    const loaded = page.waitForResponse(r => r.url().includes('/api/auth/config') && r.request().method() === 'GET')
    await page.getByRole('button', { name: '全局密钥' }).click()
    await loaded
    const dialog = page.getByRole('dialog', { name: '全局密钥' })
    await dialog.getByLabel('API 密钥').fill('e2e-fake-key')
    await dialog.getByRole('button', { name: '保存' }).click()
    await expectToast(page, '已保存')
    await clearToasts(page)
  })

  test('02 剧本页：空状态 → 转剧本（SSE）', async ({}, testInfo) => {
    await page.goto(`/#/projects/${pid}/novel`)
    await nav(page, '剧本').click()
    await expect(page).toHaveURL(new RegExp(`#/projects/${pid}/script`))
    await expect(page.getByRole('heading', { name: '剧本', exact: true })).toBeVisible()
    await expect(page.getByText('还没有剧本')).toBeVisible()
    await page.getByRole('button', { name: '转剧本', exact: true }).click()
    await expectToast(page, '剧本转换完成：2 场')
    await expect(page.getByRole('status', { name: '提取进度' })).toContainText('剧本转换完成：2 场')
    await expect(page.locator('.scene-card')).toHaveCount(2)
    await expect(page.getByRole('heading', { name: '第 1 场 · 暴雨萧瑟演武场 · 黄昏外' })).toBeVisible()
    await expect(page.locator('.scene-card').first()).toContainText('你也配站在这里？')
    // 台词类型标签：心声 / 当面
    const firstLines = page.locator('.scene-card').first().locator('.scene-card__lines li')
    await expect(firstLines.filter({ hasText: '再忍一忍。' }).locator('.scene-card__kind')).toHaveText('心声')
    await expect(firstLines.filter({ hasText: '你也配站在这里？' }).locator('.scene-card__kind')).toHaveText('当面')
    await expect(nav(page, '剧本').locator('.side-nav__count')).toHaveText('2')
    await expect(page.getByRole('button', { name: '重新转剧本' })).toBeVisible()
    await snap(page, testInfo, 'script-converted')
    await clearToasts(page)
  })

  test('03 场次编辑：改地点、增删台词、保存后刷新仍在', async ({}, testInfo) => {
    const card = page.locator('.scene-card').nth(1)
    await card.getByRole('button', { name: '编辑' }).click()
    await card.getByLabel('地点').fill('演武场东侧')
    await card.getByLabel('时间 / 内外景').fill('夜外')
    // 删掉第 2 句，末尾加一句
    await card.getByRole('button', { name: '删除第 2 句' }).click()
    await card.getByRole('button', { name: '加一句' }).click()
    const lines = card.locator('.dialogue-editor__row')
    await expect(lines).toHaveCount(3)
    await lines.nth(2).locator('textarea').fill('你给我等着！')
    await choose(page, lines.nth(2).locator('.el-select').first(), '赵虎')
    // 第 3 句类型改成“画外”
    await choose(page, lines.nth(2).locator('.el-select').nth(1), '画外')
    await snap(page, testInfo, 'scene-editing')
    await card.getByRole('button', { name: '保存这一场' }).click()
    await expectToast(page, '已保存')
    await expect(page.getByRole('heading', { name: '第 2 场 · 演武场东侧 · 夜外' })).toBeVisible()
    await expect(card).toContainText('你给我等着！')
    await expect(card).not.toContainText('赵虎捂着手腕连退三步')
    await clearToasts(page)

    await page.reload()
    const again = page.locator('.scene-card').nth(1)
    await expect(again).toContainText('演武场东侧')
    await expect(again.locator('.scene-card__lines li')).toHaveCount(3)
    await expect(again.locator('.scene-card__lines li').last()).toContainText('赵虎画外你给我等着！')
  })

  test('04 新增一场、删除一场', async () => {
    await page.getByRole('button', { name: '新增一场' }).click()
    await expect(page.locator('.scene-card')).toHaveCount(3)
    const card = page.locator('.scene-card').nth(2)
    await expect(card.getByLabel('地点')).toHaveValue('新场景')
    await card.getByRole('button', { name: '取消' }).click()
    await card.getByRole('button', { name: /更多操作/ }).click()
    await page.locator('.el-dropdown-menu__item:visible', { hasText: '删除这一场' }).click()
    await answerBox(page, '删除')
    await expectToast(page, '已删除')
    await expect(page.locator('.scene-card')).toHaveCount(2)
    await expect(nav(page, '剧本').locator('.side-nav__count')).toHaveText('2')
    await clearToasts(page)
  })

  test('04b 转剧本设置：叙事人称与目标时长存作品，随转剧本提交', async ({}, testInfo) => {
    const side = page.locator('.split__side')
    await choose(page, side.locator('.form-field', { hasText: '叙事人称' }).locator('.el-select'), '第三人称')
    await expectToast(page, '转剧本设置已保存')
    await clearToasts(page)
    const target = side.locator('.form-field', { hasText: '目标时长' })
    await target.locator('input').fill('120')
    await target.locator('input').press('Enter')
    await expectToast(page, '转剧本设置已保存')
    await expect(target).toContainText('台词合计不超过约 540 字')
    await clearToasts(page)
    await snap(page, testInfo, 'script-settings')

    // 刷新后仍在（存在作品里）
    await page.reload()
    await expect(page.locator('.split__side .form-field', { hasText: '叙事人称' }).locator('input')).toHaveValue('第三人称')
    await expect(page.locator('.split__side .form-field', { hasText: '目标时长' }).locator('input')).toHaveValue('120')

    // 重新转剧本：请求里带上人称和目标时长
    const req = page.waitForRequest(r => r.url().includes('/api/scripts/convert'))
    await page.getByRole('button', { name: '重新转剧本' }).click()
    await answerBox(page, '覆盖并转换')
    const body = (await req).postDataJSON()
    expect(body.person).toBe('third')
    expect(body.target_seconds).toBe(120)
    await expectToast(page, '剧本转换完成：2 场')
    await expect(page.locator('.scene-card')).toHaveCount(2)
    await clearToasts(page)
  })

  test('05 小说页：有剧本时一键提取基于剧本', async ({}, testInfo) => {
    await nav(page, '小说').click()
    await expect(page.getByText('已有剧本 2 场')).toBeVisible()
    const split = page.waitForResponse(r => r.url().includes('/api/shots/split') && r.request().method() === 'POST')
    await page.getByRole('button', { name: '一键提取' }).click()
    await expectToast(page, '正在按剧本（2 场）提取')
    const res = await (await split).json()
    expect(res.data.source).toBe('script')
    await expectToast(page, '一键提取完成')
    await expect(nav(page, '角色').locator('.side-nav__count')).toHaveText('3')
    await snap(page, testInfo, 'novel-extract-from-script')
    await clearToasts(page)
  })

  test('06 设置 → 模型：新建文生图模型', async ({}, testInfo) => {
    await page.locator('.project-layout__settings').click()
    await expect(page).toHaveURL(/#\/settings\/models/)
    await page.getByRole('button', { name: '新建模型' }).click()
    const dialog = page.getByRole('dialog', { name: '新建模型' })
    await dialog.locator('.el-radio-button', { hasText: '文生图' }).click()
    await expect(dialog.getByText('思考档位')).toHaveCount(0)
    await dialog.getByLabel('名称').fill('e2e 文生图')
    await dialog.getByLabel('模型 ID').fill('cogview-3-flash\nglm-image')
    await dialog.getByRole('button', { name: '保存' }).click()
    await expectToast(page, '已保存')
    await page.getByRole('group', { name: '按模型类型筛选' }).getByRole('button', { name: '文生图' }).click()
    const row = page.locator('.el-table__row', { hasText: 'e2e 文生图' })
    await expect(row).toContainText('文生图')
    await expect(row).toContainText('cogview-3-flash、glm-image')
    await expect(page.locator('.el-table__row', { hasText: 'glm-4.5-flash' })).toHaveCount(0)
    await snap(page, testInfo, 'settings-models-image')
    await clearToasts(page)
  })

  test('07 角色页：出图设置选文生图模型，生成三视图带上所选模型', async ({}, testInfo) => {
    await page.goto(`/#/projects/${pid}/characters`)
    await expect(page.getByRole('heading', { name: '角色' })).toBeVisible()
    await page.getByRole('button', { name: '批量生成的更多操作' }).click()
    await page.locator('.el-dropdown-menu__item:visible', { hasText: '出图设置' }).click()
    const dialog = page.getByRole('dialog', { name: '出图设置' })
    await expect(dialog.getByText('角色三视图提示词')).toBeVisible()
    await choose(page, dialog.locator('.el-select').first(), 'e2e 文生图（glm-image）')
    await expect(page.locator('.el-select-dropdown:visible')).toHaveCount(0)
    await snap(page, testInfo, 'assets-image-model')
    await dialog.getByRole('button', { name: '保存' }).click()
    await expect(page.locator('.page-header__subtitle')).toContainText('出图：e2e 文生图（glm-image）')

    const req = page.waitForRequest(r => r.url().includes('/api/assets/generate'))
    const resp = page.waitForResponse(r => r.url().includes('/api/assets/generate'))
    await page.getByRole('button', { name: '生成三视图' }).first().click()
    const body = (await req).postDataJSON()
    expect(body.model).toBe('glm-image')
    expect(body.model_id).toMatch(/^[0-9a-f]{24}$/)
    const data = (await (await resp).json()).data
    expect(data.model).toBe('glm-image')
    expect(data.size).toEqual([1728, 960])
    await expectToast(page, '三视图已生成')
    await clearToasts(page)

    // 设置按作品记住：刷新后仍在
    await page.reload()
    await expect(page.locator('.page-header__subtitle')).toContainText('出图：e2e 文生图（glm-image）')
  })

  test('08 分镜页：出图设置与资产页共用，生成画面带上所选模型', async () => {
    await page.goto(`/#/projects/${pid}/shots`)
    await expect(page.getByRole('heading', { name: '分镜' })).toBeVisible()
    const req = page.waitForRequest(r => r.url().includes('/api/image/generate'))
    await page.getByRole('button', { name: /生成画面$/ }).first().click()
    expect((await req).postDataJSON().model).toBe('glm-image')
    await expectToast(page, '画面已生成')
  })
})
