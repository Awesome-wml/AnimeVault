# 桌面版后端打包（L-05）

把 `backend/desktop_entry.py` 及全部依赖用 Nuitka 编译成 standalone 目录，并随包带 mongod 和 Playwright 驱动。
设计背景见 `docs/license-design.md` 第 10~12 节、`docs/spike-mongod.md`。

状态标注：**[实测]** 在 macOS arm64 上跑过；**[未实测]** 只按文档/推断写，需要在对应平台验证。

## 构建（macOS，已实测）

前置：
- Xcode Command Line Tools（`xcode-select -p` 有输出即可，本机 clang 17）；
- Python 3.12 的虚拟环境，装好 `backend/requirements.txt` 的依赖，再装 Nuitka：
  `uv pip install --python ~/.local/dongai-venv/bin/python nuitka ordered-set zstandard`（不要装进系统 Python）；
- 官方社区版 mongod 二进制（版本和下载校验见 `docs/spike-mongod.md`），arm64 和 x64 要分别准备、分别出包。

```
export DONGAI_MONGOD_BIN=~/.local/dongai-spike/bin-arm64/mongodb-macos-aarch64-7.0.48/bin/mongod
~/.local/dongai-venv/bin/python desktop/build_backend.py --clean      # 可加 --lto、--jobs N、--no-fixtures、--ffmpeg-dir <含 ffmpeg/ffprobe 的目录>
~/.local/dongai-venv/bin/python desktop/smoke_test.py                  # 冒烟（用系统 python3 也行，只用标准库）
```

构建脚本会先做版本同步与检查（见下文「版本号」），并把版本、平台（`mac-arm64`/`mac-x64`/`win-x64`，默认按本机探测，可用 `--platform` 指定）、渠道（`--channel`，默认 `stable`）写进产物。

首次构建会让 Nuitka 从 nuitka.net 下载 ccache 到 `~/Library/Caches/Nuitka`（`--assume-yes-for-downloads`）。
首次编译 1202 个 C 文件（本机 14 核，几分钟，未精确计时），有 ccache 后完整重新构建 1 分 45 秒。产物都不提交：
`desktop/build/`（中间文件）、`desktop/dist/`（成品），已在 `.gitignore`。

## 产物结构

```
desktop/dist/dongai-backend/
├─ dongai-backend            # 入口可执行文件（desktop_entry 编译而成）
├─ bin/mongod                # 随包 mongod（Windows 为 bin/mongod.exe）
├─ bin/ffmpeg, bin/ffprobe   # 可选，构建时 --ffmpeg-dir 指定（Windows 为 .exe）
├─ licenses/mongodb/         # mongod 的 LICENSE-Community.txt、THIRD-PARTY-NOTICES 等（SSPL 分发要求）
├─ playwright/driver/        # node + package/ + playwright.sh（Windows 为 node.exe + playwright.cmd）
├─ core/prompts/*.json       # 提示词数据文件
├─ tests/fixtures/           # 替身供应商夹具（DONGAI_FAKE_PROVIDERS=1 用，正式包可用 --no-fixtures 去掉）
└─ Python、*.so、*.dylib 等   # Nuitka standalone 运行时与第三方扩展
```

运行：`dongai-backend`（桌面模式默认开启 `DONGAI_DESKTOP=1`）。
- 未设置 `MONGODB_URL`：先用 `DONGAI_MONGOD_BIN`（未设置则取包旁 `bin/mongod`）拉起 mongod，数据放 `<数据目录>/mongo/`，日志 `<数据目录>/logs/mongod.log`，
  等到可 ping 才启动后端；就绪后 stdout 打印 `{"event":"ready","port":..,"token":..}`。
- 设置了 `MONGODB_URL`：不拉起 mongod，直接用它。
- 退出（正常、异常、SIGTERM、SIGINT）都会停 mongod。后端被 `kill -9` 时来不及停，`<数据目录>/mongod.pid` 记着 pid，
  下次启动先检查 pid 文件和 `mongo/mongod.lock` 里的进程：存活且命令行含 mongod 才结束（先 SIGTERM，10 秒后 SIGKILL），然后再启动。
  mongod 没有"父进程消失后自行退出"的选项，所以靠 pid 文件。
- mongod 只绑 127.0.0.1，**这一版没有开认证**：本机其他程序可以连上这个端口。认证（或改用 unix socket）是后续独立任务。
- `dongai-backend --selfcheck`：不启动服务，打印 Playwright 驱动路径/版本/可执行性，并实际 `sync_playwright().start()` 再停止（主线程和子线程各一次），退出码 0 表示通过；不会打开浏览器。

## macOS 与 Windows 的差异

| 项 | macOS | Windows（**[未实测]**） |
|---|---|---|
| 构建机 | 本机 | 必须在 Windows 上或 Windows CI 上构建，Nuitka 不能交叉编译 |
| C 编译器 | Xcode CLT（clang） | MSVC（Visual Studio Build Tools）或让 Nuitka 下载 MinGW64（需 `--assume-yes-for-downloads`；杀软对 MinGW 产物误报更多，建议 MSVC） |
| Python | python.org 的 3.12 可用 | 同样用 python.org 的 3.12（Microsoft Store 版不行） |
| mongod | `bin/mongod`（arm64 / x64 分开） | `bin/mongod.exe`，官方 zip 里取 `mongod.exe`；VC++ 运行库依赖要确认（spike 文档里的待办） |
| Playwright 驱动 | `node` + `playwright.sh` | `node.exe` + `playwright.cmd`；脚本已按平台选择，但没跑过 |
| 控制台 | 命令行程序 | 建议 `--windows-console-mode=disable`（发布）；调试用 `force`。脚本里目前是 `attach`；注意禁用控制台后 stdout 管道仍可被 Electron 读取需要验证 |
| 图标/版本信息 | 无（命令行程序，.app 由 Electron 外壳负责） | `--windows-icon-from-ico=...`、`--windows-company-name`、`--windows-product-name`、`--windows-file-version`、`--windows-product-version`，对减少杀软误报和 SmartScreen 信誉有帮助 |
| 进程清理 | `os.kill` + `ps -p` 查命令行 | 用 `tasklist` 查映像名、`os.kill`（即 TerminateProcess）结束；mongod 优雅停止走 shutdown 命令 |
| 签名 | 之后 L-09：所有嵌套可执行文件（含 node、mongod、`.so`/`.dylib`）统一重签并开 hardened runtime | L-10：后端 exe、mongod.exe、node.exe 都要签名 |

Windows 还缺：真机构建一次并解决可能出现的隐式导入差异；冒烟脚本是 POSIX 版（用了 `pgrep`、信号），需要写 Windows 版（`tasklist`/`taskkill`）；
`cleanup_stale_mongod` 在 Windows 上的 `tasklist` 判断没跑过；console 模式与 Electron 读 stdout 的配合；杀软/防火墙弹窗。

## 遇到的问题和解决（macOS 实测）

1. **`FATAL: data file ... playwright/driver/node conflicts with exe`**：Nuitka 把 `node`（Mach-O）当成可执行文件，又从包数据里当数据文件带一次，冲突。
   解决：不加 `--include-package-data=playwright`（Nuitka 自带的 playwright 配置已带上 `driver/package` 共 269 个文件），并加 `--noinclude-data-files=playwright/driver/node`，构建后由脚本从 site-packages 把整个 `driver/` 原样复制进包（保留官方 node 原件和执行权限）。
2. **`playwright/driver/playwright.sh` 缺失**：Nuitka 不会带 `.sh` 文件，`sync_playwright().start()` 报 `FileNotFoundError`（Playwright 1.40 通过这个脚本启动 node）。这是 `--selfcheck` 实测发现的，同样靠构建后复制整个 `driver/` 解决；`--selfcheck` 现在把这个文件也列入必检项。
3. 替身供应商（`DONGAI_FAKE_PROVIDERS=1`）从 `<包根>/tests/fixtures` 读占位图/音频/视频（`core/providers/fake.py` 用 `__file__` 推算路径），Nuitka 不会带这个目录，构建脚本显式复制。
4. 其余隐式导入（uvicorn 的 h11/httptools/websockets 协议实现、uvloop、passlib 的 handler、jose 的 cryptography 后端、motor/pymongo/bson、dnspython）靠 `--include-package` 整包带上，冒烟里没有缺模块。没有逐包验证过"是否带多了"，体积还有收窄空间。
5. `dongai_license`（`license/` 下的共享库）目前后端还没有 import，已经通过 `PYTHONPATH` + `--include-package` 带上，等 L-26 接入时无需再改构建。

## 已知问题与数据（本机 arm64，Nuitka 4.3.5，无 LTO）

- 包体积 430 MB（`du -sh`）：mongod 160 MB、后端可执行文件约 114 MB、playwright（node 约 89 MB + JS 约 10 MB）约 99 MB，其余是 Python 运行时和扩展。安装包压缩后会明显小于这个数。开 `--lto` 和进一步收窄 `--include-package` 可以再小一点，没做。
- 启动耗时：新构建的可执行文件第一次启动到 ready 实测 7.7 秒和 4.9 秒（两次构建各一次，含 mongod 拉起、首次建索引）；之后再启动约 0.9~1 秒。第一次慢的原因没有深挖，**[推断]** 是 macOS 对新生成的未签名可执行文件首次运行的扫描和库加载；签名后是否改善待 L-09 之后复测。
- 内存（空闲，刚做完冒烟请求）：后端进程 RSS 约 186 MB，mongod 约 106 MB，合计约 290 MB。
- Redis：桌面模式（`DONGAI_DESKTOP=1`）下强制禁用，`RedisClient.connect()` 不发起任何连接、忽略 `REDIS_URL`，`/health` 恒为 `redis: disabled`（冒烟脚本已断言）。后端只有启动/关闭/`/health` 三处用到 Redis，没有业务缓存读写，无需降级逻辑。
- `RedisClient.connect()` 等处用 `print` 输出带 emoji 的中文，Windows 上 stdout 若是 GBK 管道可能编码报错，需要在 Windows 上验证（或统一设 `PYTHONIOENCODING=utf-8`/`PYTHONUTF8=1`）。
- ffmpeg/ffprobe：`backend/bin/ffmpeg.zip` 是 404 的 HTML，没被用到。后端经 `backend/core/ffmpeg_locator.py` 找 ffmpeg（环境变量 → 包内 `bin/` → 系统 PATH），构建时用 `--ffmpeg-dir` 随包带；`--selfcheck` 会检查并打印版本。调用点、LGPL 构建来源与许可证义务见 `docs/ffmpeg-bundling.md`（**随包用哪个构建需法务确认，勿把 GPL 构建（Homebrew、gyan.dev、evermeet）打进发布包**）。
- Chrome 的拉起（Playwright `channel='chrome'`）不在本任务范围，见 L-07。

## 测试构建与授权验收（L-29）

桌面模式强制授权且不认环境变量公钥，冒烟测试需要「测试构建」：`build_backend.py --test-public-key <pub.json>`。产物带测试标记，不得发布；发布前用 `desktop/check_release_build.py` 校验正式包。完整步骤与实测输出见 `docs/license-e2e.md`。

## 版本号与更新（版本管理客户端侧）

完整规则与发布流程见 `docs/versioning.md`，这里只列和打包相关的部分。

- **单一来源**是仓库根 `VERSION`（`x.y.z`）。`build_backend.py` 构建前运行 `desktop/sync_version.py`：把 `VERSION` 同步到 `desktop/shell/package.json`（以及 `package-lock.json` 顶层版本），再检查一致；之后在编译前生成 `backend/core/_build_meta.py`（VERSION/PLATFORM/CHANNEL，已 gitignore，编译后删除），所以产物里 `core/version.py` 读到的是写死的值，不依赖仓库文件。
- **`--build-info`** 多了 `version`（不带 +testbuild）、`app_version`（测试构建带 `+testbuild`，兼容旧字段）、`platform`、`channel`；`dist/BUILD_INFO.json` 同样带这些字段，原有的 `test_build`/`marker`/`kids` 保留。
- **Electron 壳**：`npm run dist:mac|dist:win|pack` 前会先跑 `node scripts/check-version.js`（npm 的 `pre*` 钩子），`VERSION` 与 `package.json` 不一致时构建失败。单独检查：`python3 desktop/sync_version.py --check` 或 `npm run check:version`。
- **发布前检查** `desktop/check_release_build.py` 增加第 5 项：`VERSION`、壳 `package.json`、`BUILD_INFO.json`、`--build-info` 的版本一致，且平台是三种发布平台之一。
- **应用内下载更新包**（保守方案，未做静默热更新）：渲染进程调用 `window.dongaiDesktop.downloadUpdate()`（preload 白名单，无参数），主进程自己向后端取 `/api/update/status` 的 `latest`，下载到系统「下载」目录，边下边算 sha256，不一致就删除并报错；通过后 `.dmg` 直接打开，其余（`.exe`）在文件夹中显示，由用户手动安装。地址只允许 https，开发/测试构建额外允许 `http://127.0.0.1`。逻辑在 `shell/src/update-download.js`（纯函数，`npm test` 里有单测）。
- 冒烟 `smoke_test.py` 增加 2a2：未激活时 `/api/update/status` 可访问，版本/平台/渠道与 `--build-info` 一致。
