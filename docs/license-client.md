# 客户端授权（L-26 / L-41）说明

范围：联网激活 + 在线租约（定时续租、离线宽限、时钟回拨、只读降级）+ 后端全局拦截 + 前端激活页与全局提示条。租约存储加固（系统钥匙串）是 L-27。

## 后端

- `core/license_client.py`：`LicenseClient.activate / renew / status / deactivate / touch`；存储只走 `LicenseStore` 接口（授权码 + 租约记录），默认 `FileLicenseStore`（`<数据目录>/license/license.json`，权限 600）。老版本只有授权码的文件按「需要联网重新激活」处理，不放行。
- `core/license_config.py`：授权服务地址 `DEFAULT_SERVER_URL`（占位 `https://license.example.com`，**发版前替换**）。`DONGAI_LICENSE_SERVER` 只在 `DONGAI_LICENSE_DEV=1` 且非桌面模式才能覆盖，桌面模式一律忽略（与公钥规则一致）。HTTP 用 httpx，超时 10 秒，强制校验 TLS 证书。
- `core/license_renewer.py`：`LicenseRenewer` 后台线程，在 `main.py` 的 lifespan 里启动/停止；桌面模式启用，非桌面模式设 `DONGAI_LICENSE_RENEW=1` 才启用。
- `core/license_keys.py`：内置公钥 `PUBLIC_KEYS`，当前是开发用占位项，替换流程见文件头注释。
- `DONGAI_LICENSE_PUBKEYS`（JSON）只在 `DONGAI_LICENSE_DEV=1` 且非桌面模式时才覆盖内置公钥；桌面模式一律忽略。
- `core/license_guard.py`：桌面模式（`DONGAI_DESKTOP=1`）一律拦截；非桌面仅 `DONGAI_LICENSE_ENFORCE=1` 时拦截。放行 OPTIONS、`/health`、`/docs`、`/openapi.json`、`/static/*`、`/api/license/*`。出错按未授权处理。只读降级见下表。
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

WebSocket 在非 valid/grace 状态一律拒绝。前端路由守卫：valid/grace 正常进入；只读状态可进入工作台查看并随时去激活页；完全拦截状态只能进激活页。

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

- 后端：`cd backend && ~/.local/dongai-venv/bin/python -m pytest -q tests/test_license_client.py tests/test_license_renew.py`（不需要 Mongo）。`test_license_renew.py` 把客户端经 httpx MockTransport 接到真实的 `license-server`（内存仓库）上，用注入的时钟推进时间；找不到 `../license-server` 时整个文件跳过。
- 前端单测：`cd frontend && npm run test:unit`。
- 授权 e2e：`scripts/e2e-license.sh`（最小后端 + 前端 dev server，端口 8001/8081，不连数据库）。
