# 客户端授权（L-26）说明

范围：离线激活 + 后端全局拦截 + 前端激活页。在线续租是 L-41，租约存储加固（系统钥匙串）是 L-27。

## 后端

- `core/license_client.py`：`LicenseClient.activate / status / deactivate`；存储只走 `LicenseStore` 接口，默认 `FileLicenseStore`（`<数据目录>/license/license.json`，权限 600）。
- `core/license_keys.py`：内置公钥 `PUBLIC_KEYS`，当前是开发用占位项，替换流程见文件头注释。
- `DONGAI_LICENSE_PUBKEYS`（JSON）只在 `DONGAI_LICENSE_DEV=1` 且非桌面模式时才覆盖内置公钥；桌面模式一律忽略。
- `core/license_guard.py`：桌面模式（`DONGAI_DESKTOP=1`）一律拦截；非桌面仅 `DONGAI_LICENSE_ENFORCE=1` 时拦截。放行 OPTIONS、`/health`、`/docs`、`/openapi.json`、`/static/*`、`/api/license/*`。出错按未授权处理。
- 中间件顺序（请求方向）：CORS → 本地令牌 → 授权拦截 → 业务。

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

- 后端：`cd backend && ~/.local/dongai-venv/bin/python -m pytest -q tests/test_license_client.py`（不需要 Mongo）。
- 前端单测：`cd frontend && npm run test:unit`。
- 授权 e2e：`scripts/e2e-license.sh`（最小后端 + 前端 dev server，端口 8001/8081，不连数据库）。
