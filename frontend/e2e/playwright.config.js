// 端到端测试配置。一般通过仓库根的 scripts/e2e.sh 运行（它会起好后端、前端并设置下列环境变量）。
//   E2E_BASE_URL     前端地址，默认 http://localhost:8081
//   E2E_REPORT_DIR   HTML 报告目录，默认 e2e-report（相对 frontend/）
//   E2E_REAL=1       只跑真实模型冒烟（real-smoke.spec.js），超时放宽
const path = require('path')
const { defineConfig } = require('@playwright/test')

const REAL = process.env.E2E_REAL === '1'
const reportDir = process.env.E2E_REPORT_DIR || path.join(__dirname, '..', 'e2e-report')

module.exports = defineConfig({
  testDir: __dirname,
  testMatch: REAL ? ['real-smoke.spec.js'] : ['main-flow.spec.js', 'empty-states.spec.js'],
  // 主流程各步共享同一个页面，必须串行
  workers: 1,
  fullyParallel: false,
  retries: 0,
  // 真实模型一次调用可能 2–3 分钟
  timeout: REAL ? 15 * 60 * 1000 : 60 * 1000,
  expect: { timeout: REAL ? 5 * 60 * 1000 : 10 * 1000 },
  outputDir: path.join(reportDir, 'artifacts'),
  reporter: [
    ['list'],
    ['html', { outputFolder: path.join(reportDir, 'html'), open: 'never' }]
  ],
  use: {
    baseURL: process.env.E2E_BASE_URL || 'http://localhost:8081',
    // 本机没装 Playwright 自带 chromium，用系统 Chrome
    channel: 'chrome',
    headless: true,
    // 不走系统代理，直连本机前后端
    launchOptions: { args: ['--no-proxy-server'] },
    viewport: { width: 1440, height: 900 },
    locale: 'zh-CN',
    actionTimeout: 15 * 1000,
    // 真实模式不录 trace：trace 会记下请求体，其中有写入的模型密钥
    trace: REAL ? 'off' : 'retain-on-failure',
    screenshot: 'only-on-failure'
  }
})
