// 授权管理端 e2e：真实联调（内存仓库的授权服务 + vue dev server）。
//   cd license-admin && npm run e2e
// 密码不写进仓库：没设 E2E_ADMIN_PASSWORD 时本次运行随机生成。
const path = require('path')
const crypto = require('crypto')
const { defineConfig } = require('@playwright/test')

process.env.E2E_ADMIN_PASSWORD = process.env.E2E_ADMIN_PASSWORD || crypto.randomBytes(12).toString('hex')

const root = path.join(__dirname, '..')
// 端口可用 E2E_FRONT_PORT / E2E_LICENSE_PORT 覆盖（本机已有进程占用默认端口时用）
const FRONT_PORT = Number(process.env.E2E_FRONT_PORT) || 5180
const API_PORT = Number(process.env.E2E_LICENSE_PORT) || 18100
process.env.E2E_FRONT_PORT = String(FRONT_PORT)
process.env.E2E_LICENSE_PORT = String(API_PORT)

module.exports = defineConfig({
  testDir: __dirname,
  testMatch: ['*.spec.js'],
  workers: 1,
  fullyParallel: false,
  retries: 0,
  timeout: 60 * 1000,
  expect: { timeout: 10 * 1000 },
  outputDir: path.join(__dirname, '.runtime', 'artifacts'),
  reporter: [['list']],
  webServer: [
    {
      command: 'python3 e2e/start_server.py',
      cwd: root,
      url: `http://127.0.0.1:${API_PORT}/health`,
      reuseExistingServer: false,
      timeout: 60 * 1000
    },
    {
      command: 'npx vue-cli-service serve',
      cwd: root,
      env: { PORT: String(FRONT_PORT), LICENSE_API_TARGET: `http://127.0.0.1:${API_PORT}` },
      url: `http://127.0.0.1:${FRONT_PORT}/`,
      reuseExistingServer: false,
      timeout: 120 * 1000
    }
  ],
  use: {
    baseURL: `http://127.0.0.1:${FRONT_PORT}`,
    channel: 'chrome',
    headless: true,
    launchOptions: { args: ['--no-proxy-server'] },
    viewport: { width: 1280, height: 800 },
    locale: 'zh-CN',
    actionTimeout: 15 * 1000,
    trace: 'off',
    screenshot: 'only-on-failure'
  }
})
