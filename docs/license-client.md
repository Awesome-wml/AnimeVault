# 客户端授权（L-26 / L-41）说明

范围：联网激活 + 在线租约（定时续租、离线宽限、时钟回拨、只读降级）+ 后端全局拦截 + 前端激活页与全局提示条。租约存储加固（系统钥匙串 + 加密文件）是 L-27，见下文「存储加固」。

## 后端

- `core/license_client.py`：`LicenseClient.activate / renew / status / deactivate / touch`；存储只走 `LicenseStore` 接口（授权码 + 租约记录），桌面模式默认 `SecureLicenseStore`（见「存储加固」）；非桌面默认 `FileLicenseStore`（`<数据目录>/license/license.json`，权限 600），可用 `DONGAI_LICENSE_STORE=secure|file|memory` 切换，桌面模式强制 secure、忽略该变量。老版本只有授权码的文件按「需要联网重新激活」处理，不放行。
- `core/license_config.py`：授权服务地址 `DEFAULT_SERVER_URL`（占位 `https://license.example.com`，**发版前替换**）。`DONGAI_LICENSE_SERVER` 只在 `DONGAI_LICENSE_DEV=1` 且非桌面模式才能覆盖，桌面模式一律忽略（与公钥规则一致）。HTTP 用 httpx，超时 10 秒，强制校验 TLS 证书。
- `core/license_renewer.py`：`LicenseRenewer` 后台线程，在 `main.py` 的 lifespan 里启动/停止；桌面模式启用，非桌面模式设 `DONGAI_LICENSE_RENEW=1` 才启用。
- `core/license_keys.py`：内置公钥 `PUBLIC_KEYS`，当前是开发用占位项，替换流程见文件头注释。
- `DONGAI_LICENSE_PUBKEYS`（JSON）只在 `DONGAI_LICENSE_DEV=1` 且非桌面模式时才覆盖内置公钥；桌面模式一律忽略。
- `core/license_guard.py`：桌面模式（`DONGAI_DESKTOP=1`）一律拦截；非桌面仅 `DONGAI_LICENSE_ENFORCE=1` 时拦截。放行 OPTIONS、`/health`、`/docs`、`/openapi.json`、`/static/*`、`/api/license/*`、`/api/update/*`。出错按未授权处理。只读降级见下表。
- 中间件顺序（请求方向）：CORS → 本地令牌 → 授权拦截 → 业务。

## 状态表（`GET /api/license/status` 的 `state`）

| state | 含义 | 怎么进入 | 怎么离开 | 守卫 |
|---|---|---|---|---|
| `unactivated` | 未激活；或老版本只存了授权码（`needs_online=true`） | 没有授权码 / 无租约记录 | 联网激活 | 完全拦截 |
| `valid` | 租约未过期、授权未到期 | 激活或续租成功 | - | 放行 |
| `grace` | 租约已过期，仍在 72 小时离线宽限内（`grace_until` = 租约到期 + 72h） | 本地计算 | 联网续租成功 | 放行 |
| `lease_expired` | 超出宽限，需联网 | 本地计算，或服务端返回 `LEASE_EXPIRED`（落盘，不再自动重试） | 续租成功 / 重新激活 | 只读 |
| `expired` | 授权到期 | 本地到期时间已过，或服务端 `LICENSE_EXPIRED` | 管理员延期后续租成功（每小时自动重试） | 只读 |
| `suspended` | 授权被停用 | 服务端 `LICENSE_SUSPENDED`（落盘） | 管理员恢复后续租成功（每小时自动重试） | 只读 |
| `revoked` | 授权被吊销，本地授权码和租约已清除 | 服务端 `LICENSE_REVOKED`（落盘） | 换新授权码激活 | 完全拦截 |
| `session_conflict` | 授权在另一台设备被激活，本机被顶掉 | 服务端 `LICENSE_SESSION_CONFLICT`（落盘，不再自动重试） | 用授权码重新激活（会让对方下线） | 完全拦截 |
| `clock_rollback` | 检测到系统时间被回拨 | 本地计算 | 联网续租成功（以 server_time 重建时间基准） | 完全拦截 |
| `machine_mismatch` | 机器码不匹配 | 本地验证或服务端 `LICENSE_MACHINE_MISMATCH`（落盘，不再重试） | 换本机的授权码 | 完全拦截 |
| `invalid` | 无效：签名被改、未知密钥、存储读取失败、服务端 `LICENSE_INVALID`（清除本地授权） | - | 重新激活 | 完全拦截 |
| `update_required` | 强制升级（**守卫层状态**，不是 `/api/license/status` 的 `state`，授权状态本身不变）：版本低于服务端要求的最低版本 | 授权服务对 activate/renew 返回 426 `UPDATE_REQUIRED`；或更新检查返回 `force=true` / 本机版本低于 `min_supported` | 升级到要求的版本（本地比较，自动解除）；来源是更新检查的，服务端不再要求时下次检查也会解除 | 完全拦截（见下） |

服务端明确拒绝的状态（suspended/expired/machine_mismatch/session_conflict/lease_expired/revoked/invalid）会写入存储，
**重启后仍然生效，不会因为租约还没到期就放行**，直到续租成功或重新激活。任何计算异常按 `invalid` 处理（fail closed）。

## 授权到期 / 套餐 / 功能点的可信来源（H1）

租约 payload（格式 v=2）里**已签名**携带 `lexp`（授权到期时间）、`plan`、`features`、`cv`（授权码版本）。客户端：

- 授权是否到期：`可信当前时间 >= lexp` → `expired`（只读）；租约自身 `exp` 过期但 `lexp` 未到 → 仍走 `grace` / `lease_expired`，逻辑不变；
- `/api/license/status` 的 `plan` / `features` / `expires_at`（= `lexp`）都从租约签名字段推导；
- 服务端响应 JSON 的 `license.*` **不在签名内、不可信**：不参与决策，也不落盘（存储记录里不再有 `license` 副本，旧记录里的该字段会被忽略）；
- **优先级**：授权码 payload 里也有 exp/plan/features，与租约冲突时**以租约为准**（租约是服务端最新的判断）。授权码只用来离线验真、匹配机器码、取 `lid`；仅在没有可验签的租约时，状态里的 plan/features 才回退显示授权码里的值，此时状态不会是 valid/grace；
- `cv` 变大说明管理员重签/延期过，客户端无需动作，只落盘到记录的 `cv` 字段并写一条诊断日志；
- 破坏性变更：v=1 旧租约被共享库拒绝（`LicenseInvalid`），本机存着旧租约会显示 `invalid`，重新激活即可。

`status` 的附加字段：`grace_until`、`lease_expires_at`、`readonly`、`last_renew_ok_at`、`needs_online`。

## 各状态下功能可用性

| 状态 | 查看/导出已有数据（GET/HEAD） | 新建、编辑、删除（POST/PUT/PATCH/DELETE） | 视频/出图/LLM 调用（均为 POST） | 激活页和 `/api/license/*` |
|---|---|---|---|---|
| valid / grace | 可用 | 可用 | 可用 | 可用 |
| expired / suspended / lease_expired（只读） | 可用 | 403 `LICENSE_READONLY` | 403 `LICENSE_READONLY` | 可用 |
| unactivated / invalid / machine_mismatch / revoked / session_conflict / clock_rollback | 403 `LICENSE_REQUIRED` | 403 `LICENSE_REQUIRED` | 403 `LICENSE_REQUIRED` | 可用 |
| update_required（优先于上面所有授权状态） | 403 `UPDATE_REQUIRED` | 403 `UPDATE_REQUIRED` | 403 `UPDATE_REQUIRED` | 可用（`/api/license/*`、`/api/update/*`、`/health` 放行） |

WebSocket 在非 valid/grace 状态一律拒绝。前端路由守卫：valid/grace 正常进入；只读状态可进入工作台查看并随时去激活页；完全拦截状态只能进激活页。

## 版本上报、更新检查与强制升级

- **请求体字段**：`POST /license/v1/activate` 与 `/renew` 的请求体都带 `app_version`、`platform`、`channel`（`LicenseClient._client_info()`）。取值来自 `core/version.py`：版本读仓库根 `VERSION`（打包后读构建时写入的 `_build_meta.py`），测试构建带 `+testbuild`；平台 `mac-arm64|mac-x64|win-x64`；渠道默认 `stable`。
- **更新检查**（`core/update_checker.py`）：`GET {授权服务地址}/license/v1/update?version=&platform=&channel=`，返回 `{update_available, latest:{version,notes,url,sha256,size,published_at}|null, force, min_supported}`。授权服务地址与公钥同源（`license_config.update_url()`，桌面模式不认环境变量）。**搭在续租线程上**：`LicenseRenewer` 构造时传入 `update_checker` 即启用（`get_renewer()` 默认传），启动后立即检查一次，之后每个续租周期（6 小时）一次，失败 5～10 分钟后重试；失败静默，只记日志（异常类型），保留上一次成功的结果，不影响使用。未激活时同样检查。
- **接口**：`GET /api/update/status` 返回当前版本 + 缓存的检查结果（不联网）：`current_version, platform, channel, update_available, latest, force, min_supported, update_required, required_message, checked_at, check_failed, test_build`；`POST /api/update/check` 手动检查（每分钟最多 3 次）。两者都在授权白名单（`/api/update/*`），授权未激活、需要升级时也能访问。`latest.url` 不是 https 的（开发/测试构建额外允许 `http://127.0.0.1`）会被置空，不下发给前端。
- **强制升级** `update_required`：
  - 来源 1：授权服务对低于 `min_supported` 的 activate/renew 返回 HTTP 426 `{"code":"UPDATE_REQUIRED","message","min_supported"}`。`LicenseClient._post` 抛 `LicenseUpdateRequired`（`LicenseServerError` 子类），构造时就写入强制升级状态；`/api/license/activate`、`/renew-now` 把它映射成 426 返回前端；续租线程对它 1 小时后再试。**授权状态、授权码、租约都不动**，所以升级后不用重新激活。
  - 来源 2：更新检查返回 `force=true`（且有更新），或本机版本低于 `min_supported`。
  - 记录 `{min, for_version, source}`：有 `min` 时「当前版本 < min」才要求升级，升级后自动解除；426 没带 `min_supported` 时只在当前版本上要求，换版本即解除；来源是更新检查的记录在下次检查不再要求时清除，426 来源的只能靠升级解除。桌面模式落盘 `<数据目录>/update_state.json`（重启后立即生效，不必等下一次联网），非桌面只存内存。
  - 守卫（`core/license_guard.py`）：优先于授权状态判断；除 `/api/license/*`、`/api/update/*`、`/health`、`/docs`、`/openapi.json`、`/static/*`、OPTIONS 和所有非 `/api` 页面外，**所有方法的 `/api` 请求（含 GET）与 WebSocket** 一律 403 `{"code":"UPDATE_REQUIRED","state":"update_required","min_supported","message","detail"}`。不是只读，是完全拦截；只拦请求，本地数据（作品、授权存储、数据目录）原封不动。
- **前端**：`api.update.status/check`；顶部提示条 `UpdateBanner`（可稍后——按版本记忆 / 查看更新说明 / 去更新）与授权横幅同在 `App.vue` 的 `.app-bars` 粘顶容器里上下排列；强制升级时 `UpdateRequiredScreen` 全屏盖住应用（当前版本、需要的最低版本、更新说明、下载按钮、重新检查）。拦截器收到 403/426 `UPDATE_REQUIRED` 立即切到全屏页，不弹错误提示。设置 → 授权信息里显示「当前版本」并有「检查更新」按钮。
- **下载与安装**：桌面版由 Electron 主进程下载并校验 sha256，再打开安装包让用户手动安装，见 `desktop/README.md` 与 `docs/versioning.md`；浏览器环境只在新窗口打开 https 下载地址。

## 激活与续租时序

```
激活   用户粘贴授权码 → 离线验签/机器码/到期（失败直接返回，不打服务端）
        → POST /license/v1/activate → 校验返回的租约签名/lid/机器码
        → 保存 授权码 + 租约 + server_time + 本地墙钟/单调时钟锚点     （网络不通：503 LICENSE_SERVER_UNREACHABLE，不保存）

续租   LicenseRenewer：启动立即检查，之后每 60 秒检查一次是否到期
        - 距上次成功 ≥ 6 小时，或租约剩余 < 12 小时，或已过期/宽限中/时钟回拨 → POST /license/v1/renew
        - 成功：更新租约、server_time、时间基准，清除阻断标记
        - 网络错误/5xx/异常响应：5～10 分钟（带抖动）后重试，状态不变
        - 429：1 分钟后重试
        - 业务错误码：按状态表落盘；suspended/expired 每小时重试一次，其余不再自动重试
手动   POST /api/license/renew-now（每分钟最多 3 次），前端「立即检查」按钮
```

## 时钟回拨检测

- 每次联网成功记录 `server_time`、本地墙钟 `wall_at`、单调时钟 `mono_at`；之后「可信当前时间 = server_time + 经过的时间」，租约到期、宽限都按它算，本机时间偏差不影响正常使用；
- 墙钟比记录的最大墙钟（`wall_at` 与续租线程每分钟刷新的 `wall_max`）早超过 5 分钟 → `clock_rollback`，必须联网续租成功才恢复；
- 同一进程内还用单调时钟校验：单调时钟比墙钟多走 5 分钟以上同样视为回拨（跨进程重启后单调时钟不可比，靠落盘的墙钟判断）；
- 取经过时间时用墙钟与单调时钟的较大者（系统睡眠时单调时钟可能不走）。
- 代价：合法的 NTP 校时若把时间向后调超过 5 分钟，离线时也会进入 `clock_rollback`，联网续租后恢复。

## 存储加固（L-27）

实现：`core/license_store.py` 的 `SecureLicenseStore`，业务代码仍只经 `LicenseStore` 接口访问。`GET /api/license/status` 多一个 `storage_mode`（`secure` / `fallback`，文件存储为 `file`），只给授权信息页看，不弹提示。

- **整份状态加密**：授权码、租约、`server_time`、`wall_at`、`wall_max`、各状态标记序列化后用 AES-256-GCM 加密并认证，落到 `<数据目录>/license/license.enc`（权限 600，目录 700）。文件头 `DAL1 | 模式 | 12 字节随机 nonce`。
- **数据密钥在系统钥匙串**：`keyring` 库，服务名 `DongAI`，账户名 `license-<数据目录路径哈希前 12 位>`（隔离的数据目录、多用户互不串号）。macOS 走 Keychain，Windows 走凭据管理器（DPAPI 保护），Linux 走 Secret Service。
- **AAD 绑定本机**：附加认证数据 = 固定前缀 + 机器码分量（排序后）的 SHA-256 + 模式字节。文件被编辑、截断、改模式字节都认证失败；拷到另一台机器，即使数据密钥也被一起拷走也解不开。任何读取失败（认证失败、密钥丢失、格式损坏）都抛 `LicenseStoreError`，客户端状态为 `invalid`，要求重新激活（fail closed）。
- **写入**：先写临时文件、fsync，再 `os.replace`；写入失败旧文件不动。进程内 `RLock` + `license.lock` 文件锁（POSIX `flock`；Windows 仅进程内锁），续租线程的 `touch()` 与请求线程的读改写互不丢更新。`touch()` 仅在 `wall_max` 比已存值推进 ≥60 秒时才落盘。
- **降级模式**：钥匙串不可用（Linux 无 Secret Service、无头环境、用户拒绝授权）时**不会写明文**，数据密钥改为 `HKDF-SHA256(机器码分量, 盐 = 数据目录内 license/store.salt 的 32 随机字节)`，`storage_mode = "fallback"`，日志一条 warning（不含秘密）。强度低于钥匙串：同机同用户的人拿到盐文件和机器码分量就能自己派生密钥。已有 secure 文件时钥匙串突然不可用，**不会降级写入**，直接按存储不可用处理；钥匙串恢复后下一次写入自动升级为 secure。
- **迁移**：首次读写发现旧版明文 `license.json`（L-26/L-41 格式）时，导入→加密写入→读回验证→覆盖零字节后删除旧文件；`suspended` 等标记原样保留。迁移失败保留旧文件、本次按存储错误处理，下次重试，不丢授权信息。secure 模式下迁移成功会在钥匙串写一个 `<账户>-migrated` 标记；之后再出现 `license.json`（比如被人放回一份改过的）一律忽略并删除。
- **清除**：`clear()` 删除加密文件、旧明文文件和钥匙串里的数据密钥。

### 威胁模型

能提高成本的：
- 直接编辑存储文件（改小 `wall_max` 绕过回拨检测、改 `license.expires_at` 缓存、改状态标记）：认证失败 → `invalid`；
- 把整个数据目录拷到别的电脑：机器码分量不同，解不开；
- 删掉加密文件后放回旧明文文件：secure 模式下被迁移标记挡住。

防不住的（如实写明）：
- 有管理员/root 权限且能在本机用户会话下调用钥匙串的人，能取出数据密钥、自己解密、改完再加密（机器码分量也能在本机算出来）；降级模式下连钥匙串都不用；
- 调试器、读进程内存、注入、替换或打补丁后端二进制（跳过校验）；
- 回滚：把旧的加密文件（含旧的、更小的 `wall_max`）连同之前的状态整体换回去，AEAD 不能防重放；
- 虚拟机快照/整机还原。

所以本地存储只是加一层门槛。真正的防线是服务端租约签名（客户端只信签名过的租约）和机器码绑定（一授权一台、换机要服务端重新签发），租约到期后必须联网续租。

### Nuitka 打包要点

- 依赖 `keyring==25.7.0`、`cryptography`，见 `backend/requirements.txt`。
- `desktop/build_backend.py` 的第三方整包列表里带上 `keyring`（等价 `--include-package=keyring`），把 `keyring.backends.macOS` / `Windows` 等后端模块都编进去。
- 代码里**按平台显式创建后端**（macOS `macOS.Keyring()`、Windows `WinVaultKeyring()`），不依赖 entry point 自动发现，因为打包后 `importlib.metadata` 的 entry point 元数据不一定在；Linux 才用 `keyring.get_keyring()`，拿到 `fail` 后端按「不可用」走降级。
- 打包产物里要实机跑一遍 `backend/scripts/check_keystore.py`（会写入并删除一个 `DongAI-selfcheck-*` 临时条目，不碰已有条目；系统弹授权窗口时需点允许，默认 20 秒超时）。macOS 签名/公证后换了签名身份，旧条目的访问授权会重新询问一次。

## 打包时如何带上共享库 `dongai_license`

`license_client.py` 先 `import dongai_license`，失败时把仓库内 `<repo>/license` 加入 `sys.path` 再导入。打包（L-05，PyInstaller 等）时二选一：
1. 把 `license/dongai_license` 目录作为数据/隐藏导入一起打进后端包（`--paths license --hidden-import dongai_license`）；
2. 或安装成包（`pip install ./license`）后正常打包。
依赖 `cryptography`（见 `license/requirements.txt`），需要同时进入后端依赖。

## 前端外壳如何注入本地令牌

桌面外壳在页面脚本运行前（preload / `Page.addScriptToEvaluateOnNewDocument` / `initializationScript`）注入其一，值与后端 `DONGAI_LOCAL_TOKEN` 相同：

```js
window.__DONGAI_LOCAL_TOKEN__ = '<token>'
// 或
window.dongaiDesktop = { localToken: '<token>' }
```

前端 `src/utils/localToken.js` 会给 axios 与 SSE（fetch）请求统一加 `X-DongAI-Local-Token`；没有注入则不加。

## 测试

- 版本管理：`cd backend && ~/.local/dongai-venv/bin/python -m pytest -q tests/test_update_check.py`（版本比较、更新检查各分支含失败静默、426/force 进入 update_required、守卫白名单、请求体版本字段，全部 httpx MockTransport，不联网）；Electron 下载校验：`cd desktop/shell && npm test`（`node --test`，sha256 不符/非 https 被拒）；前端 `tests/unit/update.test.mjs`。
- 后端：`cd backend && ~/.local/dongai-venv/bin/python -m pytest -q tests/test_license_client.py tests/test_license_renew.py tests/test_license_store.py`（后者用内存钥匙串后端，不碰真实钥匙串）（不需要 Mongo）。`test_license_renew.py` 把客户端经 httpx MockTransport 接到真实的 `license-server`（内存仓库）上，用注入的时钟推进时间；找不到 `../license-server` 时整个文件跳过。
- 前端单测：`cd frontend && npm run test:unit`。
- 授权 e2e：`scripts/e2e-license.sh`（最小后端 + 前端 dev server，端口 8001/8081，不连数据库）。
