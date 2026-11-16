# DongAI 桌面外壳（L-06）

Electron 外壳：窗口 + 后端 sidecar。后端（Nuitka 打包的 FastAPI + 随包 mongod）同源提供前端页面，外壳只负责拉起后端、等它就绪、开窗口、注入本地令牌、退出时清理进程。

状态标注：**[实测]** 在 macOS arm64 上跑过；**[未实测]** 只按文档写。

## 架构

```
Electron 主进程 (src/main.js)
 ├─ sidecar.js ── 子进程: dongai-backend ── mongod
 │      stdout 读到 {"event":"ready","port":P,"token":T}
 ├─ BrowserWindow ── 先加载本地 splash.html
 │      ready 之后 loadURL http://127.0.0.1:P/   （后端用 DONGAI_FRONTEND_DIR 同源提供 frontend/dist）
 └─ preload.js ── sendSync 向主进程要令牌（只有后端同源页面拿得到）
        contextBridge → window.dongaiDesktop = { localToken, platform, version, onChromeMissing }
```

- 前端是 hash 路由，后端把 `frontend/dist` 挂在 `/`（`backend/core/frontend_mount.py`），`/api /static /docs /health` 优先。页面静态文件无需令牌，`/api/*` 需要令牌 + 授权（`license_guard` 只拦 `/api`）。
- 没有跨域问题，也不需要给前端注入 API 地址；令牌由 preload 在页面脚本运行前注入，`frontend/src/utils/localToken.js` 自动给请求加 `X-DongAI-Local-Token`。
- 窗口在 ready 之前就创建（显示启动画面，不依赖后端），但页面只在 ready 之后才加载，所以令牌一定先于页面脚本就位。

## 目录

```
desktop/shell/
├─ package.json            electron 44.11.3、electron-builder 26.15.0、playwright-core 1.65.1（精确版本）
├─ electron-builder.yml    打包配置（mac dmg+zip、win nsis、extraResources、签名钩子）
├─ resources/entitlements.mac.plist   Hardened Runtime 例外（逐条注明原因）
├─ src/
│  ├─ main.js              生命周期、窗口、IPC、重试逻辑
│  ├─ sidecar.js           拉起/停止后端（进程树）、遗留清理、错误分类
│  ├─ ready-parser.js      ready 行解析（容忍杂音与分片）、令牌脱敏
│  ├─ backend-path.js      sidecar 命令与环境变量解析
│  ├─ window-state.js      窗口大小位置记忆（损坏回退默认）
│  ├─ log-rotate.js        shell-backend.log 滚动（≤10MB，保留 5 个）
│  ├─ security.js          CSP、权限、导航限制
│  ├─ menu.js              菜单（含编辑菜单，激活页要粘贴）
│  ├─ chrome-check.js      检测系统 Chrome，经 IPC 暴露（引导 UI 属于 L-07）
│  ├─ updater.js           自动更新占位（L-65 接 electron-updater）
│  ├─ preload.js           单一预加载：同源页面注入 dongaiDesktop，本地页面只给 shellPage
│  └─ pages/splash.html, error.html
├─ test/shell.test.js      纯逻辑单测（node --test）
├─ e2e/run.js              Playwright `_electron` 真实跑通脚本
└─ screenshots/            验证截图
```

## 开发运行

```bash
cd desktop/shell
export NPM_CONFIG_CACHE=~/.local/dongai-build/npm-cache ELECTRON_CACHE=~/.local/dongai-build/electron-cache
npm install                      # 不要用默认 npm 缓存：~/.npm/_cacache 里有 root 属主文件会 EACCES
(cd ../../frontend && npm run build)   # 生成 frontend/dist（worktree 里先 ln -s 主仓库的 node_modules）
export DONGAI_BACKEND_CMD="$HOME/.local/dongai-venv/bin/python desktop_entry.py"   # 在 backend/ 目录下运行
export DONGAI_MONGOD_BIN=~/.local/dongai-spike/bin-arm64/mongodb-macos-aarch64-7.0.48/bin/mongod
export DONGAI_SHELL_USER_DATA=/tmp/dongai-dev-data   # 可选：隔离数据目录，不碰真实数据
npm start
npm test                         # 单测
```

## 打包

```bash
export DONGAI_MONGOD_BIN=...     # 官方社区版 mongod
desktop/build_all.sh             # 前端 → 后端包 → electron-builder（本机 arm64：dmg + zip）
desktop/build_all.sh --dir       # 只出 out/mac-arm64/DongAI.app，验证用
```

产物在 `desktop/shell/out/`（不提交）。后端包 `desktop/dist/dongai-backend` → `Resources/backend`，前端 `frontend/dist` → `Resources/frontend`。
x64 配置已写在 `electron-builder.yml`，**本机没有构建也没有验证**（需要 x64 后端包和 x64 mongod）。

### 签名与公证钩子（L-09 / L-10）

不在仓库放证书，也不写任何真实值。全部走环境变量，没有就跳过签名，出未签名开发包：

| 变量 | 用途 |
|---|---|
| `CSC_LINK`、`CSC_KEY_PASSWORD` | macOS Developer ID Application 证书（p12 路径/base64）与密码 |
| `APPLE_ID`、`APPLE_APP_SPECIFIC_PASSWORD`、`APPLE_TEAM_ID` | 公证；三个都有时 `build_all.sh` 自动加 `-c.mac.notarize=true` |
| `WIN_CSC_LINK`、`WIN_CSC_KEY_PASSWORD` | Windows 代码签名（L-10 可能改用云签名） |

已预置 `mac.hardenedRuntime: true` 和 `resources/entitlements.mac.plist`（Electron 主程序/Helper 用，含 `allow-jit`、`allow-unsigned-executable-memory`、`disable-library-validation`，原因写在文件注释里；L-09 实测发现没有 `allow-jit` 时 Electron 在 Hardened Runtime 下启动即崩溃）。sidecar 用 `resources/entitlements.sidecar.mac.plist`（两项，只由签名脚本使用）。嵌套二进制逐个签名、公证、钉票据、校验脚本和证书申请清单见 [`desktop/signing/README.md`](../signing/README.md)（L-09 macOS 已用 ad-hoc 签名在本机实测；L-10 Windows 未实测）。
Electron Fuses（关闭 `RunAsNode`、`--inspect` 等）发布版应翻开，**当前没有翻**，因为 e2e 的 Playwright 需要 `--inspect`/`--remote-debugging-port`（见下）。

## 环境变量

| 变量 | 作用 |
|---|---|
| `DONGAI_BACKEND_CMD` | 开发模式后端命令（支持引号、`~`）。打包版忽略它，除非 `DONGAI_SHELL_ALLOW_DEBUG=1` |
| `DONGAI_BACKEND_CWD` | 开发模式后端工作目录，默认 `<repo>/backend` |
| `DONGAI_FRONTEND_DIR` | 开发模式前端目录，默认 `<repo>/frontend/dist`；打包版固定用 `Resources/frontend` |
| `DONGAI_MONGOD_BIN` | 透传给后端（包内已带 `bin/mongod` 时不需要） |
| `DONGAI_SHELL_USER_DATA` | 覆盖 userData（自动化测试隔离用）。默认 macOS `~/Library/Application Support/DongAI`，Windows `%APPDATA%\DongAI`，与后端默认数据目录一致 |
| `DONGAI_SHELL_READY_TIMEOUT_MS` | ready 超时，默认 90000 |
| `DONGAI_SHELL_ALLOW_DEBUG` | 测试专用：允许调试端口、打包版接受 `DONGAI_BACKEND_CMD` / `MONGODB_URL` |

外壳传给后端的环境变量：`DONGAI_DESKTOP=1`、`DONGAI_DATA_DIR=<userData>`、`DONGAI_FRONTEND_DIR`。打包版会清掉继承来的 `MONGODB_URL` 和 `DONGAI_LOCAL_TOKEN`。

## 日志

`<userData>/logs/shell-backend.log`（后端 stdout+stderr 与外壳自己的记录；超过 10MB 轮转为 `.1`…`.5`，共保留 5 个旧文件）。ready 行里的令牌写盘前已脱敏为 `<redacted>`，并且任何出现该令牌值的行都会被替换。后端自己的日志在同目录的 `backend.log`、`mongod.log`。

## 安全设置

- `contextIsolation: true`、`nodeIntegration: false`、`sandbox: true`，`webSecurity` 保持默认；打包版关闭 DevTools。
- 令牌只通过 `sendSync` 发给来源是后端同源页面的 frame；启动画面/错误页拿不到令牌，它们只有「打开日志文件夹」「重试」两个 IPC，且主进程校验来源是本地页面目录。
- 导航：`will-navigate`/`will-redirect` 只放行本应用源；`window.open` 一律拒绝，`http(s)` 链接交给 `shell.openExternal`，其他协议（`file:`、`javascript:` 等）直接丢弃。禁用 webview。
- CSP（响应头，仅对后端同源的页面）：`default-src 'self'; script-src 'self' 'unsafe-eval'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; media-src 'self' blob: data:; font-src 'self' data:; connect-src 'self'; worker-src 'self' blob:; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'`。放宽的两项都有原因：`unsafe-inline` 样式（index.html 内联 style、Element UI 写 style 属性）；`unsafe-eval`（`app.js` 里第三方库用了 `new Function`）。前端没有任何外部域名脚本/字体。
- 权限：拒绝全部权限请求（摄像头、麦克风、通知、地理位置…），前端经核查不使用；唯一放行 `clipboard-sanitized-write`（激活页「复制机器码」）。
- 单实例锁；第二次启动聚焦已有窗口。
- 禁用远程调试端口：打包版带 `--remote-debugging-*`/`--inspect*` 启动时直接退出；e2e 用 `DONGAI_SHELL_ALLOW_DEBUG=1` 放行。

## 生命周期

- 退出（Cmd+Q、系统关机、SIGTERM）：先对后端 SIGTERM（Windows 用 `taskkill /T /PID`），最多等 20 秒，超时对整棵进程树 SIGKILL（含 mongod）。
- 后端运行中意外退出：自动重启最多 2 次（稳定运行 5 分钟后重新计数），仍失败显示错误页和「重启服务」按钮；崩溃时顺手结束遗留的 mongod。
- 外壳被强杀：下次启动先读 `<userData>/sidecar.pid`，结束遗留后端进程树；mongod 再由后端自己的 L-05 机制（`mongod.pid`）清理。
- macOS 关闭所有窗口不退出，点 Dock 图标重开；其他平台退出。

## 真实跑通（Playwright）

选用 Node 版 `playwright-core`（只装包，不下载浏览器；`_electron` 不需要）。

```bash
cd desktop/shell
node e2e/run.js dev            # 用 node_modules 里的 Electron 跑 src/
node e2e/run.js packaged       # 跑 out/mac-arm64/DongAI.app（先 desktop/build_all.sh --dir）
node e2e/run.js dev fail-mongo # 只跑某个场景
```

覆盖：窗口标题、激活页、令牌与 `/api`（有令牌 200、无令牌 401）、外部链接、CSP 头、权限拒绝、单实例锁、正常退出无残留、强杀后恢复、三类启动失败页（后端、Mongo、超时）、崩溃自动重试与「重启服务」、窗口状态记忆。全部使用临时 userData。

## Windows 注意事项 [未实测]

- 代码里 Windows 分支（`taskkill /T /PID`、`.exe` 路径、注册表检测 Chrome、NSIS 配置）都没有在 Windows 上跑过。
- 后端包要在 Windows 上用 `desktop/build_backend.py` 构建；mongod.exe 依赖 VC++ 运行库，安装器要带 vc_redist 或确认静态链接（见 `docs/spike-mongod.md`）。
- `sidecar.pid` 的进程名校验在 Windows 上跳过（直接按 pid 结束），未来可改用 `wmic`/`Get-Process` 校验。
- 签名（L-10）要覆盖 `DongAI.exe`、`dongai-backend.exe`、`mongod.exe`、`node.exe` 和所有 `.dll/.pyd`；Windows 的 SmartScreen 信誉需要时间积累。
- 单实例锁、`userData=%APPDATA%\DongAI`、`app.setName('DongAI')` 逻辑与 macOS 相同，但路径一致性需在 Windows 上确认。
