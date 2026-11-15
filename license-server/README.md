# DongAI 授权服务（license-server）

独立于客户端 `backend/` 的服务：独立依赖、独立库 `dongai_license`、独立进程。
设计见 `docs/license-design.md` 第 4、7、8、9 节。

共享库 `license/dongai_license/`（机器码解析、授权码签发验证）通过 `PYTHONPATH=../license` 引用，
代码里不改 `sys.path`（pytest 由 `tests/conftest.py` 设置）。

## 配置（全部来自环境变量，没有默认密钥）

| 变量 | 说明 |
|---|---|
| `LS_JWT_SECRET` | 必填，至少 32 位，占位符直接拒绝启动 |
| `LS_SIGNING_PRIVATE_KEY_FILE` | 必填，Ed25519 私钥文件路径（用 `license/scripts/gen_keys.py` 生成，**文件不得放进仓库**）。只在启动时读入内存，不写日志、不出现在任何返回里 |
| `LS_SIGNING_KID` | 可选，默认由公钥推导 |
| `LS_STORE` | `mongo`（默认）或 `memory`（仅测试和本地演示，重启丢数据） |
| `LS_MONGO_URL` / `LS_MONGO_DB` | Mongo 连接与库名，库名默认 `dongai_license`，**不要指向业务库 dongai** |
| `LS_PLANS` | 可选，套餐白名单，默认 `trial,basic,pro,enterprise` |
| `LS_FEATURES` | 可选，管理端功能点候选（仅提示，不限制），默认 `video,image,novel,voice,export_hd` |
| `LS_LEASE_TTL_SECONDS` | 可选，租约有效期，默认 86400（24 小时），最小 60；实际有效期取它与「授权到期时间 - 当前时间」的较小值 |
| `LS_RENEW_GRACE_SECONDS` | 可选，租约过期后仍允许续租的宽限期，默认 259200（72 小时） |
| `LS_EXPIRE_INTERVAL_SECONDS` | 可选，后台到期任务间隔，默认 300（5 分钟），0 表示不启动 |

## 运行

```bash
cd license-server
pip install -r requirements.txt
# 1. 创建首个管理员（交互输入密码；没有默认账号）
PYTHONPATH=../license python -m app.create_admin --username alice
# 2. 启动
PYTHONPATH=../license uvicorn app.main:create_app --factory --port 18100
```

没有 super 管理员时服务可以启动，但管理接口只能走登录（无人能登录），不会自动创建账号。

## 测试

```bash
PYTHONPATH=../license python -m pytest -q
```

仓库用例对内存和 Mongo 两种实现参数化；Mongo 部分仅当 `LS_MONGO_URL` 存在且 `LS_MONGO_DB` 含 `test` 时才跑，
否则跳过（会清空该测试库的相关集合，千万别指向正式库）。

## 接口（前缀 `/admin/api`，除 health 和 login 外都需 `Authorization: Bearer <JWT>`）

| 方法 路径 | 权限 |
|---|---|
| `GET /health` | 无 |
| `POST /admin/api/auth/login` | 无（5 次失败锁 15 分钟） |
| `GET /admin/api/auth/me` | 任意登录角色 |
| `POST /admin/api/licenses` 签发 | super, ops |
| `GET /admin/api/licenses` `?status&email&lid&page&page_size` | super, ops, readonly |
| `GET /admin/api/licenses/{lid}` | super, ops, readonly |
| `GET /admin/api/licenses/{lid}/events` `?page&page_size(<=100，默认 100)&order=desc｜asc(默认 desc)` | super, ops, readonly |
| `GET /admin/api/meta` | 任意登录角色：`{plans, features:{pattern,max_length,max_count,candidates}, dev_max, machine_code, request_rate_limit}`，管理端据此渲染套餐和功能点 |
| `POST /admin/api/licenses/{lid}/extend｜suspend｜resume｜revoke` | super, ops |
| `GET /admin/api/licenses/{lid}/devices` | super, ops, readonly。设备列表：`did、components_count、components_hint(各分量前 6 位)、first_seen_at、last_seen_at、last_ip、app_version、bound、unbound_at、is_current`，不返回分量全文 |
| `POST /admin/api/licenses/{lid}/kick` | super, ops。踢下线：`active_sid` 置空并撤销该授权全部租约，写 `session_kicked` 事件和 `license.kick` 审计；已吊销 409 `INVALID_TRANSITION`，无会话 409 `NO_ACTIVE_SESSION`。客户端下次续租收到 `LICENSE_SESSION_CONFLICT`，用授权码重新激活即可 |
| `POST /admin/api/licenses/{lid}/devices/{did}/unbind` | super, ops。设备 `bound=false`、记 `unbound_at`；若是当前会话设备同时踢下线；事件 `device_unbound`，审计 `license.device_unbind`；已解绑 409 `DEVICE_NOT_BOUND` |
| `GET /admin/api/requests` `?status=pending｜issued｜rejected&page&page_size` | super, ops |
| `POST /admin/api/requests/{id}/reject` `{reason?}` | super, ops；只能处理 pending，否则 409 `REQUEST_NOT_PENDING` |
| `POST /admin/api/requests/{id}/issue` `{plan, expires_at, features[], dev_max?, note?}` | super, ops；内部调用签发服务（复用全部校验，失败时申请单回到 pending），成功后申请单 `issued` 并记 `lid`，返回新授权（含授权码） |
| `POST /admin/api/admins`、`PUT /admin/api/admins/{id}` | super |
| `GET /admin/api/admins` `?page&page_size(<=100，默认 100)` | super |
| `GET /admin/api/audit` `?action&admin_id&page&page_size` | super, ops |

审计记录和授权事件冗余操作人用户名：`audit_logs.admin_username`、`license_events.actor_username`、`licenses.created_by_username`；
历史记录没有这些字段时接口返回 `null`，前端用 id 前 8 位兜底。

`extend` 对 expired 的处理：曾经激活过（`activated_at` 非空）的 expired 延期后回到 active；从未激活过的（只可能是历史或外部写入的记录）延期后回到 pending。
pending 授权到期未激活不会变成 expired（后台到期任务只处理 active），延期后仍是 pending。

申请单集合 `activation_reqs`：`{id, email, machine_code, mc[], dedup_key, note, status(pending/issued/rejected), created_at, ip, handled_by, handled_by_username, handled_at, lid, reason}`；
索引 `id` 唯一、`(status, created_at)`、`dedup_key` 部分唯一（仅 `status=pending`），Mongo 下并发重复提交也只会有一条未处理申请。

错误统一为 `{"code": "...", "message": "..."}`，状态机非法转换为 409 `INVALID_TRANSITION`。
审计日志只有写入和查询，没有任何修改/删除接口，仓库层也没有对应方法。

## 客户端接口 `/license/v1`（不需要管理员登录）

| 方法 路径 | 说明 |
|---|---|
| `POST /license/v1/request` | `{email, machine_code, note?}`，无需登录；每 IP 每小时 5 次（超限 `RATE_LIMITED`，无论请求是否合法都计数）；机器码用 `parse_machine_code` 校验，分量不足 2 个返回 `MACHINE_CODE_TOO_FEW`；同邮箱+同机器码已有未处理申请时幂等，不重复建单。恒返回 `{status:"pending"}`，不泄露是否重复 |
| `POST /license/v1/activate` | `{license_code, machine_components[], app_version, sid?}`，`sid` 预留、被忽略（会话 ID 由服务端生成）。成功 `{lease, expires_at, server_time, license:{plan,features,expires_at,status}}` |
| `POST /license/v1/renew` | `{lease, machine_components[], app_version}`，成功响应同上，会话 sid 不变 |
| `GET /license/v1/status` | `Authorization: Bearer <lease>` + `X-Machine-Components: a,b,c`，返回 `{status, plan, features, expires_at, session_active, lease_expires_at, server_time}`，不续租；授权被停用也返回 200（看 `status`） |

激活流程：授权码先 `normalize_input`（容忍分组、换行、小写）-> 验签 -> 按 lid 查记录 -> 授权码必须等于记录里当前有效的码
（延期会重签，旧码返回 `LICENSE_INVALID`，事件里记「旧码」）-> 状态检查 -> 设备绑定 -> 新会话 sid（`active_sid`，顶掉旧会话）-> 签发租约。
设备匹配用分量容差（至少命中 2 个），匹配时设备分量更新为最新；已绑定设备数不超过 `dev_max`。
续租不校验授权码，只校验租约签名、机器码、授权状态/到期、`sid == active_sid`；租约过期超过宽限期返回 `LEASE_EXPIRED`。
续租成功只更新 `last_seen_at / last_seen_ip / last_renew_at`，`renewed` 事件每授权每小时最多写一次。

| 错误码 | HTTP | 场景 | 客户端动作 |
|---|---|---|---|
| `LICENSE_INVALID` | 401（参数缺失为 400） | 授权码/租约签名无效、旧码、授权不存在 | 提示授权无效，让用户核对或联系我们；清除本地租约 |
| `LICENSE_MACHINE_MISMATCH` | 403 | 机器码与授权不符、设备数超过上限 | 提示授权与本机不匹配，引导换绑申请 |
| `LICENSE_EXPIRED` | 403 | 授权到期 | 提示到期，引导续费，只读 |
| `LICENSE_SUSPENDED` | 403 | 授权被停用 | 提示联系管理员；可定时重试 |
| `LICENSE_REVOKED` | 403 | 授权被吊销（终态） | 清除本地授权，回到激活页 |
| `LICENSE_SESSION_CONFLICT` | 409 | 授权已在别处激活（被顶掉） | 提示已在其他设备使用，需要时重新激活 |
| `LEASE_EXPIRED` | 401 | 租约过期超过宽限期 | 回到激活页，用授权码重新激活 |
| `RATE_LIMITED` | 429 | 激活过于频繁（每 IP 20 次/分钟，每授权 10 次/分钟） | 稍后重试，退避 |
| `VALIDATION_ERROR` | 422 | 请求字段缺失或类型不对 | 客户端 bug |

错误响应一律 `{code, message}`，message 不透露内部判断。日志只记 lid 和 sid 前 6 位，授权码和租约原文不进日志和事件。
激活限流是进程内存实现（多进程各自计数）。

## 部署注意

- 登录限流和客户端 IP 取自直连地址（`request.client.host`），不信任 `X-Forwarded-For`。放在反向代理后需在部署时用
  uvicorn `--proxy-headers --forwarded-allow-ips=<代理IP>`，否则所有请求来源都是代理地址。
- 登录限流是进程内存实现，多进程部署时各自计数，重启清零。
- JWT 无服务端吊销表：禁用管理员和重置密码立即生效（每次请求核对库里状态与 `token_valid_after`）。
