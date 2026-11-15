// 授权激活（L-26）：未授权时访问首页被重定向到激活页，粘贴无效授权码显示错误提示。
// 需要后端以 DONGAI_LICENSE_ENFORCE=1 启动（见 scripts/e2e-license.sh），否则整组跳过。
const { test, expect } = require('@playwright/test')
const { snap } = require('./helpers')

const ENFORCED = process.env.E2E_LICENSE_ENFORCE === '1'
test.skip(!ENFORCED, '后端未开启 DONGAI_LICENSE_ENFORCE=1（用 scripts/e2e-license.sh 运行）')

test.describe('授权激活', () => {
  test('未授权访问首页被重定向到激活页并显示机器码', async ({ page }, testInfo) => {
    await page.goto('/#/home')
    // 第一次打开 dev server 要冷编译，放宽等待
    await expect(page).toHaveURL(/#\/activate/, { timeout: 45 * 1000 })
    await expect(page.getByRole('heading', { name: '激活 DongAI' })).toBeVisible()
    await expect(page.getByText('把机器码发给我们，我们会给你授权码。')).toBeVisible()
    await expect(page.locator('.machine-code__group').first()).toBeVisible()
    await expect(page.getByRole('button', { name: '复制机器码' })).toBeEnabled()
    await snap(page, testInfo, 'redirected-to-activate')
  })

  test('粘贴无效授权码显示错误提示', async ({ page }, testInfo) => {
    await page.goto('/#/login')
    await expect(page).toHaveURL(/#\/activate/)
    const activate = page.getByRole('button', { name: '激活', exact: true })
    await expect(activate).toBeDisabled()
    await page.getByPlaceholder('在这里粘贴我们发给你的授权码').fill('ABCDE-FGHIJ\nKLMNO-PQRST')
    await activate.click()
    await expect(page.getByText('授权码无效，请检查是否复制完整')).toBeVisible()
    await expect(page).toHaveURL(/#\/activate/)
    await snap(page, testInfo, 'invalid-code')
  })
})
