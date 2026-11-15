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
| `GET /admin/api/licenses/{lid}`、`/events` | super, ops, readonly |
| `POST /admin/api/licenses/{lid}/extend｜suspend｜resume｜revoke` | super, ops |
| `POST /admin/api/admins`、`GET /admin/api/admins`、`PUT /admin/api/admins/{id}` | super |
| `GET /admin/api/audit` `?action&admin_id&page&page_size` | super, ops |

错误统一为 `{"code": "...", "message": "..."}`，状态机非法转换为 409 `INVALID_TRANSITION`。
审计日志只有写入和查询，没有任何修改/删除接口，仓库层也没有对应方法。

## 部署注意

- 登录限流和客户端 IP 取自直连地址（`request.client.host`），不信任 `X-Forwarded-For`。放在反向代理后需在部署时用
  uvicorn `--proxy-headers --forwarded-allow-ips=<代理IP>`，否则所有请求来源都是代理地址。
- 登录限流是进程内存实现，多进程部署时各自计数，重启清零。
- JWT 无服务端吊销表：禁用管理员和重置密码立即生效（每次请求核对库里状态与 `token_valid_after`）。
