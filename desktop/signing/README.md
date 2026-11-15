# DongAI 桌面版签名与公证（L-09 macOS、L-10 Windows）

状态标注：**[实测]** 在本机 macOS arm64（Darwin 25.3）上真跑过；**[未实测]** 只按文档写，没有环境验证。
我们**还没有** Apple Developer ID 证书和 Windows 代码签名证书（正在申请），所以：

- macOS 的「嵌套二进制逐个签名 → 校验 → 启动」用 ad-hoc 签名（`-`）真实跑通了；
- Developer ID 签名、时间戳、公证、钉票据、Gatekeeper 放行、Windows 全部签名**无法实测**，脚本写好了，拿到证书后按本文第 8 节走一遍。

仓库里不放任何证书、密码、身份字符串。设计依据见 `docs/license-design.md` 第 12 节，任务见 `docs/license-tasks.md` 的 L-09、L-10、L-11。

## 目录

| 文件 | 作用 | 状态 |
|---|---|---|
| `sign_mac.sh` | 逐个签名 .app 里的嵌套二进制 → bundle → 主应用，真实身份时公证、钉票据；`--dmg-only` 处理 dmg；`--dry-run` 只打印命令 | ad-hoc 签名部分 [实测]；公证部分 [未实测]（`--dry-run` 看过命令） |
| `verify_mac.sh` | 对 .app 或 .dmg 输出「通过/失败/跳过」清单，有失败退出码 1；`--release` 禁止 ad-hoc | [实测]（ad-hoc 包） |
| `lib_mac.sh` | 上面两个共用的函数（枚举 Mach-O、bundle、entitlements 取值） | [实测] |
| `sign_win.ps1` | signtool 签名应用目录和安装包里全部 exe/dll/pyd/node/msi，证书库或云签名透传 | [未实测] |
| `verify_win.ps1` | `signtool verify /pa /v` 全部二进制、列出未签名项、检查时间戳与签名人一致 | [未实测] |
| `../shell/resources/entitlements.mac.plist` | Electron 主程序与 Helper 的 entitlements（三项，含 allow-jit） | [实测] |
| `../shell/resources/entitlements.sidecar.mac.plist` | `Resources/` 下 sidecar（后端、mongod、playwright node）的 entitlements（两项） | [实测] |

## 1. 全流程：谁在什么时候需要什么凭据

```
  构建机（受控，Mac）                                    构建机（受控，Windows）
  ┌───────────────────────────────┐                    ┌───────────────────────────────┐
  │ 1. build_all.sh --dir         │                    │ 1. electron-builder --win --dir│
  │    前端 → 后端包(Nuitka)       │                    │    （后端包在 Windows 上构建）  │
  │    → 未签名 DongAI.app         │                    │    → 未签名 win-unpacked       │
  │    凭据：无                    │                    │    凭据：无                    │
  ├───────────────────────────────┤                    ├───────────────────────────────┤
  │ 2. sign_mac.sh  APP           │                    │ 2. sign_win.ps1 -Path win-unpacked│
  │    嵌套 Mach-O→bundle→主应用   │                    │    全部 exe/dll/pyd/node       │
  │    凭据：Developer ID 证书+私钥│                    │    凭据：EV/OV 证书的签名能力   │
  │         （钥匙串/临时钥匙串）   │                    │    （硬件令牌或云签名账号）      │
  ├───────────────────────────────┤                    ├───────────────────────────────┤
  │ 3. 公证（sign_mac.sh 内）      │                    │ 3. electron-builder --prepackaged│
  │    notarytool 提交 → 等结果    │                    │    用已签好的目录打 NSIS 安装包  │
  │    → stapler 钉票据 → spctl    │                    │    凭据：无                    │
  │    凭据：Apple ID+专用密码+Team │                    ├───────────────────────────────┤
  │          ID，或 notarytool 的   │                    │ 4. sign_win.ps1 -Path 安装包    │
  │          keychain profile       │                    │    凭据：同第 2 步              │
  ├───────────────────────────────┤                    ├───────────────────────────────┤
  │ 4. electron-builder --prepackaged│                   │ 5. verify_win.ps1             │
  │    用已签好的 .app 打 dmg + zip  │                   │    凭据：无                    │
  │ 5. sign_mac.sh --dmg-only DMG  │                    └──────────────┬────────────────┘
  │    签 dmg → 公证 dmg → 钉票据   │                                   │
  │ 6. verify_mac.sh --release     │                                   │
  └──────────────┬────────────────┘                                   │
                 └──────────────────────┬──────────────────────────────┘
                                        ▼
        7. 记录产物 SHA-256 → 8. 干净虚拟机人工验证（L-11）→ 9. 上传下载服务器，发布版本清单
           （任何一步失败都不上传）        凭据：无                      凭据：下载服务器的上传权限
```

| 步骤 | 需要的凭据 | 放在哪里 |
|---|---|---|
| macOS 签名 | Developer ID Application 证书 + 私钥 | CI 的密钥库（p12 + 口令存密钥管理，构建时导入**临时**钥匙串，用完删除） |
| macOS 公证 | `NOTARY_PROFILE`（推荐）或 `APPLE_ID`+`APPLE_APP_SPECIFIC_PASSWORD`+`APPLE_TEAM_ID` | 同上；不进仓库、不进日志 |
| Windows 签名 | 云签名服务账号凭据，或硬件令牌（人在机器前） | 云签名服务的凭据放 CI 密钥库；硬件令牌插在受控构建机上 |
| 上传 | 下载服务器权限 | CI 密钥库 |

## 2. 命令用法

### macOS

```bash
# 0. 出未签名 .app（本机 arm64；需要 DONGAI_MONGOD_BIN，见 desktop/shell/README.md）
desktop/build_all.sh --dir
export CSC_IDENTITY_AUTO_DISCOVERY=false    # 不让 electron-builder 自己再签一遍（路线 B）

# 1. 本机演练：默认 ad-hoc，不需要任何证书
desktop/signing/sign_mac.sh desktop/shell/out/mac-arm64/DongAI.app
desktop/signing/verify_mac.sh desktop/shell/out/mac-arm64/DongAI.app

# 2. 看真实签名+公证会执行什么（不改文件、不联网）
MAC_SIGN_IDENTITY="Developer ID Application: 公司名 (TEAMID)" NOTARY_PROFILE=dongai-notary \
  desktop/signing/sign_mac.sh --dry-run desktop/shell/out/mac-arm64/DongAI.app

# 3. 正式（拿到证书后）
export MAC_SIGN_IDENTITY="Developer ID Application: 公司名 (TEAMID)"   # 由使用者提供，不进仓库
export NOTARY_PROFILE=dongai-notary                                      # xcrun notarytool store-credentials 生成
desktop/signing/sign_mac.sh desktop/shell/out/mac-arm64/DongAI.app       # 签名 → 校验 → 公证 → 钉票据 → spctl
(cd desktop/shell && npx electron-builder --prepackaged out/mac-arm64/DongAI.app --mac dmg zip --arm64)   # [未实测] 用签好的 .app 打包
desktop/signing/sign_mac.sh --dmg-only desktop/shell/out/DongAI-0.1.0-arm64.dmg                         # 签 dmg → 公证 → 钉票据
desktop/signing/verify_mac.sh --release desktop/shell/out/DongAI-0.1.0-arm64.dmg                         # CI 门禁：失败退出码非 0
```

`sign_mac.sh` 的签名顺序（由内到外，错一步公证就失败）：

1. 所有「不是 bundle 主程序」的 Mach-O 逐个签（用 `file` 判断，不看扩展名）：后端 sidecar、`bin/mongod`、`playwright/driver/node`、全部 `.so/.dylib`、框架里的 `Helpers/`、`Libraries/`、`ShipIt`；深的先签。可执行文件带 entitlements（`Resources/` 下用 sidecar 版，其余用主版），库不带。
2. bundle 由深到浅：4 个 Helper `.app`、4 个 `.framework`。
3. 主应用最后签。

参数按身份自动调整：ad-hoc（`-`）用 `--timestamp=none`；真实身份用 `--timestamp`（公证强制要求安全时间戳）。都带 `--options runtime`。

**拿 `electron-builder` 出 dmg/zip 的两种路线**（`electron-builder.yml` 里有注释）：路线 A 让 electron-builder 自己签（设 `CSC_LINK`），它对 `Resources/backend` 下的 Nuitka 产物、mongod、playwright node 的覆盖**没有实测**；路线 B（推荐）是本文流程：先 `--dir` 出未签名包，自己逐个签，再 `--prepackaged` 打包。`--prepackaged` 的实际行为 [未实测]。

### Windows [全部未实测]

```powershell
# 云签名/证书库二选一。时间戳地址由 CA 或云签名服务指定
$env:WIN_TIMESTAMP_URL = "<RFC3161 时间戳地址>"

# 方式 1：证书在证书库（EV 令牌驱动、或云厂商 KSP 把证书同步到证书库后）
.\sign_win.ps1 -Path ..\shell\out\win-unpacked -CertThumbprint <SHA1指纹>

# 方式 2：透传 signtool 参数（云签名的 dlib/KSP 方式），例子见下
.\sign_win.ps1 -Path ..\shell\out\win-unpacked -SignToolArgs @('/dlib','C:\tools\Azure.CodeSigning.Dlib.dll','/dmdf','C:\tools\metadata.json')

# 只看会执行什么
.\sign_win.ps1 -Path ..\shell\out\win-unpacked -CertThumbprint 0000 -TimestampUrl http://example.invalid/ts -DryRun

# 校验
.\verify_win.ps1 -Path ..\shell\out\win-unpacked,..\shell\out\DongAI-Setup-0.1.0.exe -ExpectedPublisher "公司名"
```

**先签应用文件，再打安装包，最后签安装包**：NSIS 把应用文件压进安装包，安装包里的 exe 要在打包前就是已签名状态。

云签名调用示例（**全部未实测**，参数以各厂商当前文档为准；脚本只负责把 `-SignToolArgs` 原样放进 `signtool sign`）：

| 服务 | 方式 | 示例 |
|---|---|---|
| Azure Trusted Signing | signtool 的 dlib | `-SignToolArgs @('/dlib','<路径>\Azure.CodeSigning.Dlib.dll','/dmdf','<路径>\metadata.json')`；时间戳地址按微软文档。electron-builder 26 也内置了 `win.azureSignOptions`，不需要本脚本（也未实测） |
| DigiCert KeyLocker | 先装 Software Trust Manager 客户端并同步证书到证书库，再按证书库方式签 | `-CertThumbprint <指纹>`，或 `-SignToolArgs @('/csp','<KSP 名称>','/kc','<密钥对别名>','/f','<证书.crt>')` |
| SSL.com eSigner | 官方提供独立的 CodeSignTool（Java 命令行），不是 signtool 参数 | 要接入需要另写一层包装，或用它的 KSP/证书库方式；按官方文档 |

### 用 electron-builder 的自定义签名钩子对接 [未实测]

electron-builder 26 里自定义签名函数的位置是 `win.signtoolOptions.sign`（旧版本是 `win.sign`，按所装版本的 schema 核对），它对每个要签的文件调用一次，参数里有 `path`。示意（需要自己放到仓库并实测）：

```js
// desktop/shell/signing/builder-sign-win.js —— 示意，未实测
const { execFileSync } = require('child_process')
exports.default = async function (configuration) {
  execFileSync('powershell', ['-NoProfile', '-File', 'desktop/signing/sign_win.ps1',
    '-Path', configuration.path, '-NoVerify'], { stdio: 'inherit' })   // 证书/时间戳走环境变量
}
```

```yaml
win:
  signtoolOptions:
    sign: ./signing/builder-sign-win.js
```

这条路线对 `dongai-backend.exe`、`mongod.exe`、`node.exe`、`.pyd` 的覆盖取决于 electron-builder 是否把它们交给钩子（它默认只签应用 exe、安装器和 `signDlls` 指定的 dll），所以**推荐用 `sign_win.ps1` 对目录整体签名的路线 B**。

## 3. 本机实测记录（macOS arm64，ad-hoc）[实测]

输入：复制 L-06 已有构建产物 `desktop/shell/out/mac-arm64/DongAI.app`（Electron 44.11.3，后端 Nuitka 包，官方 mongod 7.0.48），原件不动。

- 枚举：119 个 Mach-O（77 个 `.so`、31 个动态库/框架主库、11 个可执行文件），其中 110 个单独签、8 个 bundle（4 个 Helper `.app` + 4 个 `.framework`）、1 个主应用。`sign_mac.sh` 全程约 13 秒。
- 签名前：`verify_mac.sh` 退出码 1。原始包里有 3 种签名人混在一起：Electron/后端大量文件是链接器占位的 ad-hoc 签名（`flags=0x20002(adhoc,linker-signed)`，**不算签名**），mongod 是 MongoDB 的 Team ID，playwright 的 `node` 是 Node 官方的 Team ID。
- 签名后：`codesign --verify --deep --strict` 通过；119 个 Mach-O 全部已签名且有效；签名人一致；全部带 `runtime` 标志；entitlements 与声明的两个 plist 完全一致。时间戳、spctl、stapler 三项在 ad-hoc 下自动「跳过」（`--release` 下记为失败）。
- **启动验证**：对签名后的 `.app` 直接运行 `Contents/MacOS/DongAI`，带 `DONGAI_SHELL_ALLOW_DEBUG=1`、隔离的 `DONGAI_SHELL_USER_DATA`（临时目录），拉起了 Helper（GPU/Renderer）、`dongai-backend`、`mongod`，`/health` 返回 healthy，首页 200，退出后无残留进程。
- 故意制造的问题（全部被校验脚本抓出，退出码 1）：

| 场景 | 校验脚本的报告 |
|---|---|
| 漏签：对一个 `.dylib` 执行 `codesign --remove-signature` | 「有未签名的 Mach-O」点名该文件；`--deep --strict` 同时报 `a sealed resource is missing or invalid`、`file modified: ….dylib` |
| 顺序错误：整个 app 签完后再单独重签一个 `.dylib` | 整体校验失败：封印里记录的该文件哈希已变（`file modified`），主程序校验也失败 |
| 多余 entitlement：给 mongod 加 `get-task-allow` | 「entitlements 与声明的 plist 不一致」，点名 mongod、多出的键 |
| 缺 hardened runtime：node 不带 `--options runtime` 重签 | 「缺少 Hardened Runtime 标志」点名该文件（同时 entitlements 不一致） |

- dmg：用 `hdiutil` 把签好的 `.app` 做成 dmg，`sign_mac.sh --dmg-only` 签名，`verify_mac.sh` 能校验 dmg 自身并挂载后检查里面的 `.app`，通过。**这不是 electron-builder 出的 dmg**，`--prepackaged` 路线没有实测。
- 公证相关命令只用 `--dry-run` 看过输出（密码被打码成 `***`），没有联网、没有提交。

## 4. 踩坑记录

1. **Electron 在 Hardened Runtime 下必须有 `allow-jit`**（L-06 的 plist 只有两项，漏了）。[实测] 只给 `allow-unsigned-executable-memory` + `disable-library-validation` 时，Electron 主程序启动即崩溃：`Fatal process out of memory: Failed to reserve virtual memory for CodeRange`。已在 `entitlements.mac.plist` 里补上；`electron-builder.yml` 的 `entitlements`/`entitlementsInherit` 都指向它，所以路线 A 同样受益。
2. **sidecar 需要的更少，按实测拆成了独立的 plist**（ad-hoc 下的结论）：
   - `dongai-backend`：必须 `disable-library-validation`，否则 dyld 报 `Library not loaded: @executable_path/Python … mapping process and mapped file (non-platform) have different Team IDs`；它不需要 `allow-unsigned-executable-memory`。
   - playwright 的 `node`：必须 `allow-unsigned-executable-memory`（V8），只给这一项就能跑；不需要 `allow-jit`。
   - `mongod` 7.0.48：什么都不需要。
   - 换成真实证书后，自己签的 `.so/.dylib` 与后端同 Team，`disable-library-validation` 可能可以去掉，**必须拿到证书后实测，不要凭推测删**。
3. **最容易漏签的**：`Resources/backend` 下的 Nuitka 产物——77 个 `.so`（扩展模块，`file` 报 `Mach-O 64-bit bundle`）和 `Python`、`libwebp*.dylib` 等没有 `.dylib` 后缀或带版本号后缀的库（`libz.1.3.1.zlib-ng.dylib`、`Python`）；`playwright/driver/node`、`bin/mongod`（第三方，带别人的 Team ID，必须用我们的证书重签，否则「签名人不一致」且 Library Validation 出问题）；Electron Framework 里的 `Helpers/chrome_crashpad_handler`、`app_shim_loader`，`Libraries/libffmpeg.dylib`、`libvk_swiftshader.dylib`，`Squirrel.framework/Versions/A/Resources/ShipIt`。所以枚举**必须用 `file` 判断**，不能靠扩展名（`Python`、`dongai-backend`、`node`、`mongod`、`ShipIt` 都没有扩展名）。
4. **链接器占位签名不是签名**：arm64 的 Mach-O 出厂就带 `adhoc,linker-signed`，`codesign --verify` 能过，但公证不认。校验脚本把它当「未签名」报出。
5. **不要用 `codesign --deep` 去签**（已弃用，且会把所有东西用同一套参数签，entitlements 无法区分）。本流程逐个签，bundle 不带 `--deep`。`--deep` 只用在校验上。
6. **顺序**：主应用的资源封印记录了 `Contents/Resources` 下每个文件的哈希。主应用签完后，任何文件（哪怕只是重签一个 `.dylib`）再被改动，整体校验就报 `a sealed resource is missing or invalid`。所以必须先签内层、最后签主应用；签完后不要再动里面的任何文件（包括重新压缩、`strip`、改权限以外的操作）。
7. **bundle 的主程序不要单独签两遍**：签 `.app`/`.framework` 时 codesign 会连主程序一起签。脚本通过读 `Info.plist` 的 `CFBundleExecutable` 把它们从单文件队列里剔除。
8. **框架要签目录**（`X.framework`，经 `Versions/Current` 解析），不能只签里面的主库，否则资源封印不对。
9. **ad-hoc 不能带 `--timestamp`**（没有证书，时间戳服务会拒绝；脚本在 ad-hoc 时传 `--timestamp=none`）。真实证书必须带，否则公证拒绝。
10. **启动测试要用隔离数据目录**：`dongai-backend` 不带 `DONGAI_DATA_DIR` 直接运行会在真实的 `~/Library/Application Support/DongAI` 下建库并拉起 mongod（实测中我们的一次试验就这样误建了目录，已清理）。直接运行主可执行文件时务必同时设置 `DONGAI_SHELL_USER_DATA` 和 `DONGAI_SHELL_ALLOW_DEBUG=1`（参照 `desktop/shell/e2e/run.js`）。
11. 背景启动的进程会被工具/CI 在命令结束时一起杀掉，测试启动要在**同一条命令里**启动、探活、退出。
12. 复制 `.app` 请用 `ditto` 或 `cp -R -c`，保留符号链接（`Versions/Current`）、扩展属性，不要用会解引用符号链接的工具，否则框架结构被破坏。
13. 当前 `.app` 里没有 zip/jar/whl 等压缩包（已查）；公证会解开包内压缩包检查里面的 Mach-O，以后若有依赖带进压缩包，需要先解开签好。**[未实测]** 没有提交过公证。

## 5. 证书申请清单（L-01、L-02，周期长，不依赖开发，要提前办）

### 5.1 Apple Developer Program（macOS 必需）

- [ ] 决定账号主体：**公司账号**（证书上显示公司名；需要 D-U-N-S 编号和法人/授权人验证）还是个人账号（证书上显示个人姓名，不适合对外售卖）。我们走公司。
- [ ] 办 D-U-N-S：向 Dun & Bradstreet 申请或查询公司已有编号。设计文档估计「几天到几周」，**以 Apple/D&B 实际回复为准，今天就办**。名称、地址必须和营业执照英文信息一致。
- [ ] 注册 Apple Developer Program（每年 99 美元，以 Apple 官网当前为准），Account Holder 需要能通过 Apple 的身份核验电话/邮件。
- [ ] 创建 **Developer ID Application** 证书（只有 Account Holder 能创建 Developer ID 类证书）：
  1. 本机「钥匙串访问」→ 证书助理 →「从证书颁发机构请求证书」，存到磁盘，得到 CSR；
  2. developer.apple.com → Certificates → `+` → Developer ID Application → 上传 CSR → 下载 `.cer`；
  3. 双击 `.cer` 导入**生成 CSR 的那台机器**的钥匙串（私钥在那里），确保它旁边出现私钥；
  4. 钥匙串访问「我的证书」→ 右键该证书 → 导出为 `.p12`，设一个强口令。**p12 和口令只放 CI 密钥库，不发聊天、不进仓库**；
  5. 同时需要 Apple 的 Developer ID 中间证书（Xcode 通常自带，干净 CI 机要确认钥匙串里有，否则签名链不完整）。
- [ ] 记下 **Team ID**（developer.apple.com → Membership）。
- [ ] 获取公证凭据，二选一：
  - **App 专用密码**：appleid.apple.com →「登录与安全」→「App 专用密码」→ 生成（该 Apple ID 需开启双重认证），用于 `APPLE_APP_SPECIFIC_PASSWORD`；
  - 或 **App Store Connect API Key**（`notarytool --key/--key-id/--issuer`），更适合 CI，不绑个人账号。脚本目前只实现了 keychain profile 与 Apple ID 两种，用 API Key 需要扩展 `setup_notary_auth`。
- [ ] 把凭据存成 notarytool 的 keychain profile（推荐，避免密码出现在命令行）：
  `xcrun notarytool store-credentials "dongai-notary" --apple-id <Apple ID> --team-id <TeamID>`，按提示输入专用密码。
- [ ] 证书到期提醒（Developer ID 证书有有效期，到期前续期；已签名的老包在时间戳有效时仍然有效）。

### 5.2 Windows 代码签名证书

- **EV 与 OV**：设计文档的判断是 EV 能直接获得 SmartScreen 信誉、OV 需要积累下载量。注意这一点近年业界讨论有变化，**向 CA 问清楚当前 SmartScreen 对 EV/OV 的实际差别，并以 L-11 干净 Windows 机的实测为准**，不要只信文档。
- **私钥必须放在硬件令牌或云 HSM 里**（行业规定，OV 也一样），不能是 pfx 文件。对 CI 的影响：
  - 硬件 USB 令牌：必须有人把令牌插在**受控构建机**上，并输入令牌口令，不适合无人值守的云 CI；
  - **云签名服务**（DigiCert KeyLocker、SSL.com eSigner、Azure Trusted Signing 等）：CI 里自动签名只能走这条；
  - 所以选 CA 之前先定签名发生在哪台机器上。
- **选云签名服务时要问 CA/服务商的问题**（只列问题，不写价格和周期，一律以对方书面答复为准）：
  1. 国内公司主体能不能受理？需要哪些材料（营业执照、对公账户、法人/授权人验证方式、电话回访、D-U-N-S）？
  2. 从提交到证书可用要多久？有没有加急？验证被退回一般卡在哪？
  3. 价格结构：证书年费、签名次数或按月计费、超量怎么算、多年期是否更便宜、续期要不要重新验证？
  4. 私钥在哪（云 HSM 所在地区）？能否从中国大陆构建机稳定访问？延迟、可用性 SLA？
  5. 在 CI 里怎么调用：是 signtool 的 dlib/KSP，还是它自己的命令行/API？能不能用服务账号、能不能限制只在指定机器/IP 上签？
  6. 一次能签多少文件？我们的安装包有几百个 dll/pyd，是否按文件计费、有无限速？
  7. 时间戳服务地址是什么？是否免费不限量？
  8. 证书上显示的发布者名称是什么（和公司全称一致吗）？之后能否改名？
  9. 证书到期、吊销、私钥泄露时的处理流程和时限？
  10. SmartScreen 信誉怎么继承：续期或换证书后信誉是否保留？
  11. 有没有合同/审计文件可以给我们法务看？
- [ ] 国内杀软：编译型 Python 容易被 Defender、360、火绒、腾讯电脑管家误报。每个版本发布前到微软和国内主要杀软的白名单入口提交样本（L-11 的一部分）。

## 6. CI 要求

- **密钥只放 CI 的密钥库或云签名服务**。p12、口令、专用密码、云签名 token 不进仓库、不进镜像、不进日志（`sign_mac.sh` 在 dry-run 里把 `--password` 打码；真实运行时 notarytool 的参数里有密码会出现在进程列表，所以优先用 `NOTARY_PROFILE`）。
- **签名只在受控构建机上跑**：固定的 Mac 和 Windows 构建机，限制谁能触发签名任务和改流水线；签名任务只对指定分支/tag 开放，PR 构建不给密钥。
- macOS CI 里导入证书到**临时钥匙串**，用完删除：`security create-keychain -p <随机口令> build.keychain` → `security import cert.p12 -k build.keychain -P <p12口令> -T /usr/bin/codesign` → `security set-key-partition-list -S apple-tool:,apple: -s -k <随机口令> build.keychain` → `security list-keychains -s build.keychain`。[未实测]
- **流程固定**：打包 → 签名 → 公证（Mac）→ 校验 → 计算哈希 → 上传，任何一步失败即终止，不上传。校验步骤用 `verify_mac.sh --release`、`verify_win.ps1`（退出码非 0 就让流水线失败）。
- **构建产物哈希记录**：`shasum -a 256 DongAI-*.dmg DongAI-*.zip`、`Get-FileHash -Algorithm SHA256 DongAI-Setup-*.exe`，把文件名、大小、SHA-256、构建号、git 提交、签名人、公证提交 ID 写进版本清单并随产物归档；上传后下载回来再比一次哈希。
- 证书到期要有提醒，留足续期时间（EV 续期也要重新验证）。

### 发布前干净虚拟机验证清单（对应 L-11，人工）

三台**全新**机器各一台：全新 macOS（装好系统后不装任何开发工具、不登录开发者账号）、Windows 10、Windows 11。安装包必须**经浏览器下载**（带隔离/Mark-of-the-Web 标记），不要用 U 盘或共享文件夹拷贝，那样绕过了 Gatekeeper/SmartScreen。

macOS：
- [ ] 浏览器下载 dmg，双击打开，拖入「应用程序」，**无任何「无法验证开发者」「已损坏」提示**
- [ ] 首次双击启动无拦截；`spctl --assess --type execute -vv /Applications/DongAI.app` 显示 `accepted source=Notarized Developer ID`
- [ ] **断网**重复一次安装和启动（验证票据已钉进 dmg/app，离线也不报警）
- [ ] 能进入激活页；退出后无残留进程（`dongai-backend`、`mongod`）
- [ ] Intel 包（x64）若发布，在 Intel 机器或 Rosetta 之外的真机上验证

Windows 10 / 11：
- [ ] 浏览器下载安装包，双击：**无 SmartScreen 蓝色拦截页**（或仅有可接受的提示，记录截图）
- [ ] 安装器、安装后的主程序、`dongai-backend.exe`、`mongod.exe` 的「属性 → 数字签名」都有我们的发布者名称和时间戳
- [ ] Defender 实时保护开启，无误报；国内杀软（360、火绒、腾讯电脑管家）各装一台或用沙箱各扫一遍
- [ ] 安装、启动、进入激活页、卸载，无残留
- [ ] 把样本提交到微软和各杀软白名单入口，记录提交编号

## 7. 实测 / 未实测对照

| 项 | 状态 | 说明 |
|---|---|---|
| 枚举 .app 内全部 Mach-O（file 判断）、bundle 识别、主程序剔除 | **实测** | 119 个 Mach-O、8 个 bundle |
| ad-hoc + Hardened Runtime 由内到外逐个签名 | **实测** | 13 秒，校验全部通过 |
| 签名后 `.app` 启动、sidecar 拉起、`/health` | **实测** | 隔离数据目录 |
| entitlements 是否足够（Electron 需 allow-jit；sidecar 各项） | **实测（ad-hoc 下）** | 真实证书下 `disable-library-validation` 是否可去掉未测 |
| `verify_mac.sh` 抓漏签、顺序错误、多余 entitlement、缺 runtime | **实测** | 4 个故意制造的场景 |
| dmg 签名与校验（`hdiutil` 手工制作的 dmg） | **实测** | 非 electron-builder 出的 dmg |
| 公证命令序列（submit、log、staple、validate、spctl）的拼装与打码 | **dry-run 看过输出** | 没有联网，没有提交，notarytool 输出格式的解析（`status:`、`id:`）按文档写，未对照真实输出 |
| Developer ID 真实签名（`--timestamp`、证书链、Authority 检查） | **未实测** | 没有证书；`verify_mac.sh` 里 TeamIdentifier、Timestamp 检查的真实分支未走过 |
| 公证、钉票据、`spctl` 通过、离线安装 | **未实测** | |
| `--prepackaged` 用签好的 `.app` 打 dmg/zip | **未实测** | 本机只验证了 `electron-builder.yml` 解析结果与改动前完全一致（只增加了注释） |
| arm64 + x64 / universal | **未实测** | 本机只有 arm64 构建 |
| 钥匙串导入、CI 临时钥匙串 | **未实测** | |
| `sign_win.ps1`、`verify_win.ps1`、云签名各调用示例、electron-builder `signtoolOptions.sign` 钩子 | **未实测** | 本机无 Windows、无 PowerShell，脚本连语法都没有机器检查过，只做了人工审阅 |
| Windows 上 Nuitka 后端包、NSIS 安装包 | **未实测** | |
| 干净虚拟机验证（L-11）、杀软白名单 | **未做** | 依赖证书 |

## 8. 拿到真实证书后要做的步骤

macOS（L-09 收尾）：
1. 把 p12 导入构建机钥匙串（或 CI 临时钥匙串），`security find-identity -v -p codesigning` 确认身份字符串；`xcrun notarytool store-credentials` 建 profile。
2. 先 `--dry-run` 看命令；然后对 L-06 的 `.app` 真签：`MAC_SIGN_IDENTITY=... NOTARY_PROFILE=... sign_mac.sh <app>`。
3. **用 `verify_mac.sh --release` 走一遍**，确认时间戳、签名人 TeamIdentifier、`spctl`、`stapler` 的真实分支（目前没跑过）。
4. 公证被拒时按第 9 节排查，`sign_mac.sh` 会自动打印 `notarytool log`。
5. 实测 `electron-builder --prepackaged` 出 dmg/zip，再 `--dmg-only`；核对 dmg 内 `.app` 仍通过 `verify_mac.sh --release`（`electron-builder` 重新打包不能改动 `.app` 内文件）。
6. 在真实签名下再测 entitlements：试着去掉 sidecar 的 `disable-library-validation`，看后端是否还能起（同 Team 的库应能加载）；mongod/node 的两项是否可以更少。
7. 用 `ditto -c -k --keepParent` 重新压 zip 前确认已钉票据；x64 包或 universal 包重复以上步骤。
8. 干净 Mac 上按第 6 节清单验证（L-11）。

Windows（L-10 收尾）：
1. 在 Windows 构建机上装 Windows SDK（signtool），按所选云签名服务装它的客户端/KSP/dlib，先用一个无关的测试 exe 手工 `signtool sign` + `signtool verify /pa /v` 跑通。
2. `sign_win.ps1 -DryRun` 看命令，再对 `win-unpacked` 真签，`verify_win.ps1`。
3. 确认 `.pyd`、`node.exe`、`mongod.exe` 的处理方式（全部重签，还是用 `-SkipAlreadySigned` 保留官方签名；后者要配 `verify_win.ps1 -AllowThirdParty`）。与杀软误报、SmartScreen 信誉的取舍需要在干净机上实测后决定。
4. 实测 NSIS 流程（先签目录 → `--prepackaged` 打包 → 签安装包），确认安装器与卸载器都带签名。
5. 在 CI 里接 `sign_win.ps1`，云签名凭据放 CI 密钥库。
6. 干净 Windows 10、11 验证，提交杀软白名单（L-11）。

## 9. 常见失败排查

**公证被拒（`status: Invalid`）**：`sign_mac.sh` 会自动打印 `xcrun notarytool log <id>`，日志里每条 issue 对应一个文件路径。常见原因：

| 日志里的话 | 原因与处理 |
|---|---|
| `The binary is not signed with a valid Developer ID certificate` | 用了 Apple Development / 其他证书，或仍是 ad-hoc/链接器占位签名。检查 `MAC_SIGN_IDENTITY` 是 `Developer ID Application`；`verify_mac.sh` 看签名人。**漏签的嵌套二进制**（`.so`、`.dylib`、mongod、node、Helper）是最常见原因 |
| `The signature of the binary is invalid` | 签名后文件又被改动（顺序错误、重压缩、`strip`），或封印失效。重新按顺序整体重签 |
| `The executable does not have the hardened runtime enabled` | 缺 `--options runtime`。`verify_mac.sh` 的 Hardened Runtime 项会点名文件 |
| `The signature does not include a secure timestamp` | 缺 `--timestamp`（ad-hoc 或网络访问不了 Apple 时间戳服务）。构建机要能访问 `timestamp.apple.com` |
| `The binary uses an SDK older than the 10.9 SDK` | 某个第三方二进制太旧。本包扫描过 `.so/.dylib/可执行文件` 都 ≥ 11，换依赖版本后需要重查：`otool -l <文件> \| grep -A4 LC_BUILD_VERSION` |
| `The executable requests the com.apple.security.get-task-allow entitlement` | entitlements 里带了调试项。`verify_mac.sh` 的 entitlements 检查会提前抓出多余的键 |
| `The signature of the binary is not valid for the architecture` / 通用二进制问题 | 胖二进制各架构分别签名；`lipo -archs` 检查 |
| 压缩包内的未签名 Mach-O | 公证会解开 zip/jar/tar 检查，把它们先解开签好（当前 `.app` 里没有） |

**其他**：

- `security find-identity` 找不到身份：p12 没导入、私钥丢失（`.cer` 导进了另一台机器）、临时钥匙串未加入搜索列表。
- `errSecInternalComponent`：钥匙串锁定或没执行 `set-key-partition-list`。
- `spctl` 报 `rejected`：未公证、票据没钉（dmg 与 .app 都要钉）、或测试包带了隔离标记但未联网。先看 `stapler validate`。
- 签名后启动即崩溃：先看崩溃信息，`Failed to reserve virtual memory for CodeRange` = 缺 `allow-jit`；dyld `different Team IDs` = 缺 `disable-library-validation` 或有第三方库没重签。
- Windows：`SignTool Error: No certificates were found that met all the given criteria` → 证书不在当前证书库或令牌没插/没解锁；`The specified timestamp server either could not be reached or returned an invalid response` → 时间戳地址或网络问题，可重试或换 CA 提供的备用地址；`signtool verify` 报 `A certificate chain could not be built` → 构建机缺中间证书或根证书；NSIS 安装包签了名但里面的 exe 未签 → 顺序错了，先签目录再打包。
