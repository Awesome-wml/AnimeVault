# 版本管理（客户端侧）

范围：版本号规则、客户端怎么上报/检查版本、强制升级、应用内下载安装，以及发布流程。服务端接口与管理端「版本发布」页由 license-server / license-admin 实现，这里只写客户端依赖的契约。

## 版本规则

- **单一来源**：仓库根 `VERSION`，一行 semver：`x.y.z`（例：`0.1.0`）。预发布可写 `x.y.z-rc.1`；不要写 `+build` 元数据，`+testbuild` 由构建脚本加。
- **正式版** `x.y.z`；**测试构建**（`build_backend.py --test-public-key`）的版本号后面带 `+testbuild`（`0.1.0+testbuild`），不得发布；`check_release_build.py` 会拒绝带 `+testbuild` 的正式包。
- **比较**按 semver 优先级（`core/version.py: compare_versions`）：先比 x、y、z；同号时预发布 < 正式版；`+build` 不参与。
- **平台** `mac-arm64 | mac-x64 | win-x64`；**渠道** 默认 `stable`（构建参数 `--channel` 写入，小写字母数字、`-`、`_`，最长 32）。
- 谁读它：
  - 后端 `core/version.py`：源码运行读 `VERSION`；打包产物读构建时生成的 `core/_build_meta.py`（不入库）。
  - Electron 壳 `desktop/shell/package.json` 的 `version`：构建脚本从 `VERSION` 同步（`desktop/sync_version.py`），不一致时构建失败。**不要手改 package.json 的版本，改 `VERSION`。**
  - 前端：`GET /api/update/status` 的 `current_version`（设置 → 授权信息里显示）。

## 客户端行为

| 行为 | 说明 |
|---|---|
| 上报 | activate / renew 请求体带 `app_version`、`platform`、`channel` |
| 更新检查 | 搭续租线程：启动后一次，之后每 6 小时一次；`GET /license/v1/update?version=&platform=&channel=`；失败静默 |
| 提示条 | 有新版本显示「发现新版本…」：稍后（记住该版本，下个版本再提示）/ 查看更新说明 / 去更新 |
| 强制升级 | 426 `UPDATE_REQUIRED` 或检查返回 `force=true` / 低于 `min_supported`：除授权、更新、health 外所有 `/api` 403 `UPDATE_REQUIRED`，前端全屏升级页；本地数据不动，升级后无需重新激活。细节见 `docs/license-client.md` |
| 下载 | 桌面版：主进程下载到系统「下载」目录 → 校验 sha256（不符删除并报错）→ `.dmg` 打开 / `.exe` 在文件夹中显示 → 用户手动安装。浏览器环境：新窗口打开 https 下载地址 |
| 地址限制 | 下载地址只允许 https；开发/测试构建额外允许 `http://127.0.0.1`；重定向逐跳检查，不允许降级到 http |

### 服务端契约（客户端依赖）

```
GET /license/v1/update?version=0.1.0&platform=mac-arm64&channel=stable
200 {"update_available": true,
     "latest": {"version","notes","url","sha256","size","published_at"} | null,
     "force": false, "min_supported": "0.1.0" | null}

POST /license/v1/activate | /renew   低于 min_supported 时
426 {"code":"UPDATE_REQUIRED","message":"...","min_supported":"x.y.z"}
```

`sha256` 必须是 64 位十六进制（小写大写都行），缺失则客户端拒绝应用内下载。`size` 可选，有则校验。

## 发布流程

1. **改 `VERSION`**（例如 `0.1.0` → `0.2.0`），提交。
2. **构建**：`python3 desktop/sync_version.py`（可省略，`build_backend.py` 会自动同步并检查）→ `build_backend.py`（不带 `--test-public-key`）→ `npm run dist:mac|dist:win`（构建前自动检查版本一致）。三个平台分别在各自机器上构建，`--platform` 默认按本机探测。
3. **发布前检查**：`python3 desktop/check_release_build.py`（含版本一致性、无测试公钥、版本不带 +testbuild）。
4. **签名/公证**：按 `desktop/signing/README.md`，对 dmg / exe 签名（macOS 还要公证）。**签名之后**再算 sha256。
5. **上传** dmg/exe 到下载源（https），得到 `url`；`shasum -a 256 <安装包>` 得到 `sha256`，记下文件大小。
6. **管理端「版本发布」录入**：版本号、平台、渠道、`url`、`sha256`、`size`、更新说明（`notes`）、发布时间；需要强制升级旧版本时设置 `min_supported`（或勾选 `force`）。确认后**发布**。
7. **验证**：用旧版本客户端点「设置 → 授权信息 → 检查更新」，能看到提示条；下载后校验通过会打开安装包。

回滚：在管理端把该版本下架（或把 `latest` 指回上一版）；已经被设置的 `min_supported` 要一并调低，否则旧客户端仍会被要求升级。客户端的强制升级状态在版本满足要求后自动解除，不需要用户操作。

## 升级到 electron-updater（当前没做）

现在是「应用内下载 + 校验 + 手动安装」。静默热更新用 `electron-updater`，**依赖已签名的发布与更新源**，真实证书到位后可以升级，需要：

1. **真实代码签名**：macOS 的 Developer ID + 公证（自动更新要求应用已签名，Squirrel.Mac 校验签名身份一致）；Windows 的 EV/OV 证书或云签名（`electron-updater` 校验发布者名称）。
2. **更新源**：一个 https 的 generic 源（或 S3/OSS）放 `latest-mac.yml`、`latest.yml` 和安装包；`electron-builder.yml` 配 `publish`（provider、url），构建时生成这些元数据文件（含 sha512）。与管理端「版本发布」的关系：要么让管理端发布时同时生成/上传 yml，要么让 `latest.url` 指向同一个源。
3. **macOS 需要 zip 包**（`target` 里已有 zip，Squirrel.Mac 用它更新，dmg 只用于首次安装），双架构分别发布。
4. **替换 `desktop/shell/src/updater.js` 占位**：`autoUpdater.checkForUpdates()`、`download-progress`/`update-downloaded` 事件转给渲染进程，「去更新」改成「下载并重启安装」；`autoDownload=false`，用户确认后下载；沿用 `UpdateBanner`/`UpdateRequiredScreen`，只换 `startUpdate` 的实现。
5. **后端 sidecar 的升级**：后端是外壳包里的 `resources/backend`，随外壳整体替换；升级前外壳要先停 sidecar（含 mongod），再 `quitAndInstall`；数据目录（`userData`）不在安装目录里，不受影响，但要验证数据库版本迁移。
6. **强制升级仍走现有后端机制**（426/force），electron-updater 只负责把包装上；`sha256` 校验由 electron-updater 的 sha512 取代，管理端字段保留用于手动下载兜底。
7. 测试：搭本机 generic 源 + 测试签名自测一轮；Windows 的 NSIS 增量更新、杀软拦截要真机验证。
