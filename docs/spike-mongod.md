# L-04 spike：随包 mongod 可行性验证

验证日期 2026-11-15，分支 `l04-spike`（基于 desktop-license 732874c）。本机 macOS arm64（`uname -m` = arm64）。
标注：**[实测]** 本机跑出来的；**[文档]** 来自官方文档或下载元数据；**[推断]** 我的判断，未实际验证。

## 结论

**建议走方案 A（随包带 mongod），第一版先出包，数据访问层同步收口，B 作为后续选项。**

1. **能完整支撑现有后端**：随包 mongod 7.0.48 起的实例上，后端 295 个用例全部实际运行（0 跳过），267 通过；28 个失败经核对与 Mongo 无关（见 3 节），不是兼容性问题。
2. **启动快、恢复可靠**：冷启动约 0.54 秒，空库 RSS 约 99 MB，磁盘占用约 0.1~1.3 MB；kill -9 后重启数据完整（j=true 写入和 20000 条数据都在，validate 通过）。管理器原型 15 个测试通过（含真 mongod 的 kill -9 重启集成测试）。
3. **换库代价大于收益**：后端是 22 个文件、约 5000 行里 300+ 处直接调用 motor/pymongo，ObjectId 用了 88 处，另有同步和异步两套客户端；但没有用 aggregate、$lookup、事务、change stream、$regex、GridFS。换 SQLite 估计 2~3 周加全量回归，而 A 方案的主要成本是包体（单个 mongod 约 160 MB，压缩后约 42 MB）、签名和 SSPL 法务确认，都可控。

需要你决定的事见文末。

## 1. 获取与体积

官方社区版 7.0.48（`https://downloads.mongodb.org/current.json` 里 7.0 系最新，**[文档]**）：

| 平台 | 下载地址 | 压缩包大小 | SHA256 |
|---|---|---|---|
| macOS arm64 | https://fastdl.mongodb.org/osx/mongodb-macos-arm64-7.0.48.tgz | 实测下载 | e276808c384259de99c39163147d8814f2b42e39ee1283cada29a8753fc3eb04 |
| macOS x64 | https://fastdl.mongodb.org/osx/mongodb-macos-x86_64-7.0.48.tgz | 76,362,466 B（HEAD 请求，未下载） | 990d743ac6c405e0a2713bd5ffc01966b3349a910dbf0ced05eb37484c40e54f |
| Windows x64 | https://fastdl.mongodb.org/windows/mongodb-windows-x86_64-7.0.48.zip | 636,894,850 B（HEAD，未下载，**[推断]** 含调试符号等，mongod.exe 本身会小得多） | 7f2e23e8bdd794fc89179d3e683726e75949020b3e690727a2faf1859df773ac |

注意：`downloads.mongodb.com/...enterprise...` 是企业版，不要用。

**实测（macOS arm64）**：
- 下载放在 `~/.local/dongai-spike/dl/`，解压到 `~/.local/dongai-spike/bin-arm64/`（均不在仓库内）。官方 `.sha256` 文件与 current.json 里的值一致，本地 `shasum -a 256` 校验通过后才解压使用。
- 包内容：`bin/mongod`（167,764,416 B，约 160 MiB）、`bin/mongos`（约 114 MiB）、`bin/install_compass`，另有 LICENSE-Community.txt、MPL-2、THIRD-PARTY-NOTICES、README。**包里没有 mongo shell**（7.0 起 shell 另发 mongosh）。
- 只取 `mongod` 即可，不要 mongos 和 install_compass；`gzip -c mongod | wc -c` = 41,750,158 B（约 40 MiB），安装包压缩后增量约 40 MB，装机后占 160 MB。
- 动态库依赖（`otool -L`）全是系统库：libcurl、libresolv、libSystem、CoreFoundation、Security、libc++，**没有需要随包的第三方 dylib**，是单文件。
- 瘦身空间：可以不带 mongos/compass 脚本（已计入上面）；`strip` 对已签名的 mongod 意义不大（**[推断]** 官方二进制已去符号，且 strip 会破坏签名需重签）。没有进一步瘦身手段。
- Windows 依赖 **[推断]**：mongod.exe 依赖 VC++ 运行库，官方 zip 不带，需确认安装器里带 vc_redist 或静态链接（待在 Windows 机器上验证，本次没有 Windows 环境）。

## 2. 本机实测（mongod 7.0.48，arm64）

命令（端口随机，未使用 27017，未连任何远程库）：

```
mongod --dbpath ~/.local/dongai-spike/data --bind_ip 127.0.0.1 --port <随机>
```

| 项 | 结果 |
|---|---|
| 冷启动到可 ping | 0.54 秒（三次一致） |
| 空库 RSS | 约 99 MB |
| 写入 2 万条（每条约 200 B）并建索引后 RSS | 约 121 MB |
| 磁盘占用 | 空库 0.1 MB；写入 2 万条后约 0.9 MB；多次启停后目录约 1.3 MB |
| SIGTERM 停止 | 约 0.1 秒退出，退出码 0；重启后 20000 条完整 |
| kill -9 | 写入（含 j=true 的 500 条）后 kill -9；`mongod.lock` 残留（非空）；重启 0.54 秒，日志出现 "Detected unclean shutdown - Lock file is not empty" 并自动恢复；20000 条 + 501 条全部在，`validate` 为 true |

默认内存：WiredTiger 缓存默认取（物理内存-1GB）的一半，桌面版建议 `--wiredTigerCacheSizeGB 0.25`（管理器已默认加）。**[文档]** 该参数最小 0.25。未实测加此参数后的 RSS。

## 3. 兼容性验证（后端 pytest）

命令（库名 `dongai_spike_test`，随包 mongod 实例，没有设置 STATIC_DIR / JIANYING_DRAFT_DIR）：

```
cd backend && MONGODB_URL=mongodb://127.0.0.1:<port>/ MONGODB_DB_NAME=dongai_spike_test \
  DONGAI_FAKE_PROVIDERS=1 ~/.local/dongai-venv/bin/python -m pytest -q
```

| | 通过 | 失败 | 跳过 |
|---|---|---|---|
| 不设 MONGODB_URL（基线） | 219 | 11 | 65 |
| 接随包 mongod | **267** | 28 | **0** |

即基线跳过的 65 个全部变成实际运行（219+11+65 = 267+28 = 295）。

失败归类（**[实测+判断]**，没有一条是 Mongo 报错）：
- 基线就失败的 11 个（不依赖 Mongo）：提示词文案断言（角色设定板、导演提示词、场景视角、segments 五段式）、shot_split 的模型能力表和重试逻辑断言等，是测试与代码已漂移。
- 接 Mongo 后多出的 17 个：基本都是调 `/api/shots/split`、`/api/storyboard` 等接口，测试按 JSON 解析，而接口现在返回 SSE（`data: {...}`），报 `JSONDecodeError` / `KeyError: 'shots'`；另有错误提示文案不一致（"没有可导出…" vs "没有已生成…"）。同样是测试没跟上接口变更。
- 没有 pymongo/motor 异常、没有不支持的命令或操作符。

我没有逐条修这些用例（超出 spike 范围）；建议另开任务把它们修复，否则 CI 里 Mongo 用例不能当绿线。**未验证**：与现网 Mongo 版本（不清楚是几版）的行为差异。

## 4. 许可证（SSPL）— 以下是我的理解，需要法务确认，不是结论

官方 FAQ（https://www.mongodb.com/legal/licensing/server-side-public-license/faq）里的原话：
- "The copyleft condition of Section 13 of the SSPL applies only when you are offering the functionality of MongoDB, or modified versions of MongoDB, to third parties as a service. There is no copyleft condition for other SaaS applications that use MongoDB as a database."
- Section 13 对"作为服务提供"的定义包括让第三方通过网络远程与程序功能交互、或提供一个价值主要来自该程序的服务。
- FAQ 说用户可以自由 "review, modify, distribute the software"。

我的理解：把 mongod 二进制原样随桌面软件分发、仅本机 127.0.0.1 供自己的应用使用、不对外提供 MongoDB 服务，看起来不落在 Section 13 的"作为服务提供给第三方"之内。**但**：
1. FAQ 没有直接回答"随桌面软件打包分发"这个场景，我是从 Section 13 的适用范围推出来的；
2. 分发本身要遵守许可证的常规条款（随包附 LICENSE-Community.txt、THIRD-PARTY-NOTICES，保留版权声明；官方 tgz 里已有这些文件）；
3. 如果以后做云端托管或让用户远程访问本机数据库，结论会变；
4. 官方的 SSPL 全文没逐条读完，不能替代法务意见。
另外 MongoDB 提供商业许可（OEM），若法务不放心，可以咨询官方。

## 5. 备选方案评估（只调研，不迁移）

对 `backend/`（排除 tests、scripts）grep 统计：

| 用法 | 次数 |
|---|---|
| find / find_one | 42 / 54 |
| insert_one / insert_many | 13 / 10 |
| update_one / update_many | 37 / 6 |
| delete_one / delete_many | 9 / 12 |
| count_documents | 3 |
| create_index | 10（含复合唯一索引 users.username） |
| sort / skip | 23 |
| `$set/$unset/$setOnInsert` | 44 |
| `$push/$pull/$inc/$addToSet` | 1 |
| `$in/$or/$and/$ne/$gt…` | 5 |
| ObjectId | 88 |
| aggregate / `$lookup` / `$regex` / 事务 / change stream / GridFS / find_one_and_* / bulk_write / distinct | **0** |

涉及 22 个文件，集合：projects(36)、shots(32)、characters(17)、video_sets(16)、scripts/scenes/props/llm_models(各13)、users(5)、doubao_accounts(2)。同时存在 motor 异步客户端（`db/mongo_client.py`）和同步 pymongo 客户端（`db/sync_client.py`、`doubao_account_pool.py`、若干脚本）。

判断：
- 好消息：查询形态简单（基本是 CRUD + `$set`），没有聚合和事务，文档结构扁平，理论上适合换。
- **FerretDB**：Mongo 协议兼容，底层 SQLite/Postgres，业务代码不用改；但它也是要随包的外部进程（Go 二进制）+ 底层存储，体积、签名、杀软问题和 A 一样，且兼容性需要重新验证，**[推断]** 不比直接带 mongod 省事。
- **mongita**：纯 Python、API 仿 pymongo 但是同步的，motor 的 `await` 调用要全部包一层；不支持的操作符和索引行为、并发写（后端是 async + 多请求）风险需要逐个验证。本次没有实测，**[推断]** 风险偏高。
- **自写 SQLite 数据访问层**：要抽出仓储层，改约 300 处调用点、88 处 ObjectId 语义（id 类型会影响所有接口和前端）、嵌套文档字段（JSON 列）、索引，再全量回归；估计 2~3 周（**[推断]**，含测试修复），且现有 28 个漂移用例要先修，否则回归没有可靠基线。
- 结论：第一版不换。先在 A 上出包，并把 `db.xxx.find(...)` 的散落调用逐步收口到 repository（L-04 任务本身已含），这样将来换 B 的代价才会下降。

## 6. 杀软与签名风险

- **官方二进制已签名**（实测 `codesign -dvv`）：Authority 为 `Developer ID Application: MongoDB, Inc. (4XWMY46275)`，Hardened Runtime 已开启（flags=0x10000 runtime），arm64 thin。`spctl -a -t exec` 对裸可执行文件返回 "does not seem to be an app"，这对非 .app 的二进制是正常现象，不代表有问题。
- macOS 公证 **[文档/推断]**：公证是对整个安装包（.dmg/.app）提交；公证要求包内所有可执行文件都是有效的 Developer ID 签名并开启 hardened runtime 和安全时间戳。官方 mongod 满足，但按设计文档 12.1 "所有嵌套可执行文件统一用我们自己的证书重签"更稳妥（`codesign --force --options runtime --timestamp --sign "Developer ID Application: ..."`），重签后要重新跑 `notarytool` 验证。重签是否会遇到 entitlements 问题，没有实测（没有我们的证书）。
- mongod 是 arm64 / x64 分别的二进制，两个安装包各带一份，不要混；universal 包需要 lipo 合并（官方没有 universal 包，**[推断]** 不建议合并，分开出包）。
- Windows **[推断]**：mongod.exe 官方带 MongoDB 的 Authenticode 签名（需在 Windows 上 `signtool verify` 确认，本次未验证）；我们的安装包和后端 exe 仍要用自己的 EV 证书签名。个人网络下 SmartScreen 信誉按安装包算，不按 mongod 算。
- 杀软：mongod 是本地监听端口的守护进程，可能触发 Windows Defender 防火墙弹窗和部分国产杀软的"监听端口/拉起子进程"提示。缓解：只绑 127.0.0.1（本原型已做）、从应用安装目录运行、签名齐全、提前向主流杀软厂商提交白名单。**以上均为推断，未在杀软环境实测。**
- 运行时：不要用 `--fork`（Windows 不支持）；由应用直接拉起子进程并在应用退出时 SIGTERM/shutdown，避免孤儿进程；数据目录放用户目录（macOS `~/Library/Application Support/DongAI`，Windows `%APPDATA%\DongAI`）。

## 原型代码

- `backend/desktop/mongod_manager.py`：`MongodManager(binary_path, data_dir, port=None, ...)`：`start()`、`stop()`、`ensure_running()`、`is_running`，也可作为 `with` 上下文使用。
  - 空闲端口随机选；就绪判定 = 端口可连 + pymongo ping（`ping=False` 可只查端口），超时抛 `MongodError`，启动中进程退出会立即报错并带日志路径。
  - 停止：POSIX SIGTERM，超时强杀；Windows 先发 shutdown 命令，失败再 terminate（**Windows 路径未实测**）。
  - 崩溃重启沿用原端口（连接串不变），最多 `max_restarts` 次（默认 3）。
  - 锁文件：`mongod.lock` 里 pid 仍存活则拒绝启动（防止两个 mongod 写同一目录）；pid 已死则标记 `recovered_unclean=True`、不删文件，交给 mongod 的 journal 恢复（实测恢复有效）。
  - 用集成测试发现并修了一个问题：崩溃后端口在 TIME_WAIT，需 `SO_REUSEADDR` 探测，否则重启会换端口导致连接串变化。
- `backend/tests/fake_mongod.py`：假 mongod（监听端口，可模拟启动失败、慢启动、忽略 SIGTERM、运行中崩溃）。
- `backend/tests/test_mongod_manager.py`：14 个单元测试（假进程）+ 1 个真 mongod 集成测试（`DONGAI_MONGOD_BIN` 存在才跑）。结果：无环境变量 14 通过 1 跳过；设置后 15 通过（连跑 3 次稳定）。
- 尚未做：把管理器接入 `main.py`/`settings`（属于 L-03/L-05）、`--auth`（本机 127.0.0.1 无认证，**本机其他程序理论上可连**，设计文档的一次性令牌只保护后端接口，不保护 mongod；需决定是否开启 auth 或改用 unix socket / 仅命名管道）、应用崩溃时孤儿 mongod 的清理（下次启动靠锁文件检测到存活 pid 会拒绝，需要 UX 处理）。

## 需要决定的事

1. 是否按 A 推进，以及 SSPL 随包分发是否交给法务确认（是 P0 前置）。
2. mongod 是否开启认证（本机任意程序可连 127.0.0.1 上的 mongod）。
3. 28 个已漂移的用例是否另开任务修复。
4. Windows 上的启动/签名/杀软需要在真机验证一次（本次没有 Windows 环境）。
