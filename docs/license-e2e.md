# 授权链路端到端验收（L-29）

日期 2026-11-15，macOS 26.3（arm64，Python 3.12.10，Nuitka 4.3.5，mongod 7.0.48）。下面的输出都是本机真实跑出来的原样（过长的行截断）。

## 做了什么

| 项 | 说明 |
|---|---|
| 构建期测试公钥 | `desktop/build_backend.py --test-public-key <文件> [--test-license-server http://127.0.0.1:18100]`。构建前临时生成 `backend/core/_test_build.py`（已 gitignore，编译后删除，`finally` 保证），`core/license_keys.py` 发现它就整体替换公钥并置 `TEST_BUILD`。授权服务地址只允许本机地址。与 `--skip-nuitka` 互斥。正式构建（不带该参数）会先删除遗留的测试模块 |
| 测试构建的标记 | `dongai-backend --build-info` 打印 JSON；启动时 stderr 打警告；ready 行带 `"test_build": true`；版本号带 `+testbuild`（随续租上报服务端）；`dist/BUILD_INFO.json` |
| 正式构建检查 | `desktop/check_release_build.py`：源码树无 `_test_build.py`、`BUILD_INFO.json`、实际运行 `--build-info`、产物里扫描测试标记串 `DONGAI-TEST-BUILD-`，任何一项是测试构建就 exit 1；`--expect-test` 反向断言 |
| e2e 脚本 | `scripts/license_e2e.py`（共用部件 `scripts/license_e2e_lib.py`），可重复运行，每次临时生成密钥对、临时数据目录/HOME，结束即删 |
| 冒烟测试 | `desktop/smoke_test.py` 增加 `--priv-key`：进程内起 license-server，取机器码、签发、激活后再跑原有检查 |
| 其他 | `backend/tests/license_e2e_app.py` 加了 `POST /api/projects` 占位；`backend/tests/test_license_test_build.py` 单测 |

注意：构建期间 `backend/core/_test_build.py` 存在，此时从源码运行后端也会变成测试构建；构建结束就消失。构建时请不要同时跑后端单测。

## 复现步骤

```
S=<临时目录>   # 私钥只放这里，不要放进仓库（gen_keys.py 也会拒绝写进 git 仓库）
cd license && ~/.local/dongai-venv/bin/python scripts/gen_keys.py --out $S/priv.key
#   kid: af8b6316 / public_key: bg4DZBzyOknMrOIMd5jKaSlK7IZPSDs2EOc2SsrTjNs
echo '{"kid":"af8b6316","public_key":"bg4DZBzyOknMrOIMd5jKaSlK7IZPSDs2EOc2SsrTjNs"}' > $S/pub.json
cd .. && DONGAI_MONGOD_BIN=<mongod> ~/.local/dongai-venv/bin/python desktop/build_backend.py --clean --test-public-key $S/pub.json
```
（构建约 10 分钟。本机未带 `--ffmpeg-dir`，包内没有 ffmpeg，运行时用系统 PATH 的 ffmpeg，所以冒烟测试第 8 项 SKIP。）

## 1 构建产物检查

```
$ python desktop/check_release_build.py --expect-test
[1] 源码树无 _test_build.py：是
[2] BUILD_INFO.json test_build=True
[3] --build-info：{"test_build": true, "marker": "DONGAI-TEST-BUILD-7f3a", "kids": ["af8b6316"], "license_server": "http://127.0.0.1:18100", "app_version": "1.0.0+testbuild"}
[4] 文件内扫描测试标记串：命中 ['BUILD_INFO.json', 'dongai-backend']
检查通过：产物是测试构建

$ python desktop/check_release_build.py        # 同一个产物按「正式构建」检查，必须失败
检查未通过：
 - BUILD_INFO.json test_build=True，期望 False
 - --build-info test_build=True，期望 False
 - 版本号带 +testbuild
 - 授权服务地址是本机地址：http://127.0.0.1:18100
 - 测试标记串扫描结果 ['BUILD_INFO.json', 'dongai-backend']，期望没有
rc=1
```
**没有实跑过「正式构建」产物**（只构建了测试包；正式构建要再编译约 10 分钟，且正式公钥、服务地址尚是占位）。正式构建能通过检查这一侧，只由代码路径保证：不带参数时构建脚本删除 `_test_build.py`，运行时 `license_keys.TEST_BUILD=False`（单测 `test_release_build_has_no_test_marker` 覆盖）。发版前请对正式产物实跑一次本脚本。

## 2 端到端（源码最小应用 + 内存仓库）

`~/.local/dongai-venv/bin/python scripts/license_e2e.py --store memory`

```
license-server：http://127.0.0.1:51127  store=memory  kid=8522bc2b
[PASS] 0a 未激活：status.state=unactivated  -- state=unactivated
[PASS] 0b 未激活：业务接口被完全拦截  -- 403 LICENSE_REQUIRED
[PASS] 1 客户端取机器码  -- machine_code=ANRF6-PABUV-4AEAK-BUBTM-GUSZG-QDCHS-4YILW-3DRT6-73
[PASS] 2 admin 签发授权码  -- lid=lic_de3647fc6e56ae97 status=pending code前16位=PMRGIZLWL5WWC6BC…
[PASS] 3a 乱码授权码被拒  -- 400 LICENSE_INVALID
[PASS] 3b 激活成功  -- 200 state=valid plan=pro
[PASS] 3c 服务端：授权 active、绑定 1 台设备  -- status=active devices=1
[PASS] 4 续租成功，租约有效期向后推  -- 200 state=valid lease_exp 1794832459 -> 1794832461
[PASS] 5 业务接口可用（读和写都放行）  -- GET=200 POST=200
[PASS] 6a admin 停用授权  -- 200 suspended
[PASS] 6b 客户端续租被拒：LICENSE_SUSPENDED，state=suspended 且 readonly  -- 403 LICENSE_SUSPENDED state=suspended readonly=True
[PASS] 6c 只读降级：读 200，写 403 LICENSE_READONLY  -- GET=200 POST=403 LICENSE_READONLY
[PASS] 6d 重启后仍然只读（状态已落盘）  -- state=suspended POST=403
[PASS] 7 admin 恢复 -> 续租成功，写操作恢复  -- resume=200 renew=200 state=valid POST=200
[PASS] 8a 换机（授权码绑定的是另一台机器）：客户端拒绝激活  -- 403 LICENSE_MACHINE_MISMATCH state=unactivated biz=403
activate machine_mismatch lid=lic_de3647fc6e56ae97
[PASS] 8b 服务端直接验证：同一授权码带别的机器分量激活被拒  -- 403 LICENSE_MACHINE_MISMATCH
[PASS] 9a 同机另一个实例用同一授权码激活（后激活者胜）  -- 200 state=valid
    （续租限频：等 60 秒）
[PASS] 9b 旧会话续租被拒 LICENSE_SESSION_CONFLICT，被完全拦截  -- renew=409 LICENSE_SESSION_CONFLICT state=session_conflict biz=403 LICENSE_REQUIRED
[PASS] 9c 旧会话重新激活后又换对方被顶掉（同一授权同时只有一个在线会话）  -- A activate=200 state=valid B renew=LICENSE_SESSION_CONFLICT
[PASS] 9d 服务端设备仍只有 1 台（两个实例同一机器分量）  -- devices=1
[PASS] 10a admin 吊销 -> 续租被拒 LICENSE_REVOKED，state=revoked  -- revoke=200 renew=403 LICENSE_REVOKED state=revoked
[PASS] 10b 吊销后完全拦截：读写都是 403 LICENSE_REQUIRED  -- GET=403 LICENSE_REQUIRED POST=403 LICENSE_REQUIRED
[PASS] 10c 吊销后原授权码无法再次激活  -- 403 LICENSE_REVOKED
[PASS] 11 服务端事件留痕  -- events=['issued', 'activated', 'device_bound', 'renewed', 'suspended', 'resumed', 'machine_mismatch', 'session_replaced', 'renewed', 'session_replaced', 'renewed', 'revoked']

通过 24 / 24
```

## 2 端到端（临时 mongod 作授权服务存储）

`~/.local/dongai-venv/bin/python scripts/license_e2e.py --store mongo`

```
license-server：http://127.0.0.1:51633  store=mongo  kid=15a925db
[PASS] 0a 未激活：status.state=unactivated  -- state=unactivated
[PASS] 0b 未激活：业务接口被完全拦截  -- 403 LICENSE_REQUIRED
[PASS] 1 客户端取机器码  -- machine_code=ANRF6-PABUV-4AEAK-BUBTM-GUSZG-QDCHS-4YILW-3DRT6-73
[PASS] 2 admin 签发授权码  -- lid=lic_860eeb0fd6f05753 status=pending code前16位=PMRGIZLWL5WWC6BC…
[PASS] 3a 乱码授权码被拒  -- 400 LICENSE_INVALID
[PASS] 3b 激活成功  -- 200 state=valid plan=pro
[PASS] 3c 服务端：授权 active、绑定 1 台设备  -- status=active devices=1
[PASS] 4 续租成功，租约有效期向后推  -- 200 state=valid lease_exp 1794832534 -> 1794832535
[PASS] 5 业务接口可用（读和写都放行）  -- GET=200 POST=200
[PASS] 6a admin 停用授权  -- 200 suspended
[PASS] 6b 客户端续租被拒：LICENSE_SUSPENDED，state=suspended 且 readonly  -- 403 LICENSE_SUSPENDED state=suspended readonly=True
[PASS] 6c 只读降级：读 200，写 403 LICENSE_READONLY  -- GET=200 POST=403 LICENSE_READONLY
[PASS] 6d 重启后仍然只读（状态已落盘）  -- state=suspended POST=403
[PASS] 7 admin 恢复 -> 续租成功，写操作恢复  -- resume=200 renew=200 state=valid POST=200
[PASS] 8a 换机（授权码绑定的是另一台机器）：客户端拒绝激活  -- 403 LICENSE_MACHINE_MISMATCH state=unactivated biz=403
activate machine_mismatch lid=lic_860eeb0fd6f05753
[PASS] 8b 服务端直接验证：同一授权码带别的机器分量激活被拒  -- 403 LICENSE_MACHINE_MISMATCH
[PASS] 9a 同机另一个实例用同一授权码激活（后激活者胜）  -- 200 state=valid
    （续租限频：等 59 秒）
[PASS] 9b 旧会话续租被拒 LICENSE_SESSION_CONFLICT，被完全拦截  -- renew=409 LICENSE_SESSION_CONFLICT state=session_conflict biz=403 LICENSE_REQUIRED
[PASS] 9c 旧会话重新激活后又换对方被顶掉（同一授权同时只有一个在线会话）  -- A activate=200 state=valid B renew=LICENSE_SESSION_CONFLICT
[PASS] 9d 服务端设备仍只有 1 台（两个实例同一机器分量）  -- devices=1
[PASS] 10a admin 吊销 -> 续租被拒 LICENSE_REVOKED，state=revoked  -- revoke=200 renew=403 LICENSE_REVOKED state=revoked
[PASS] 10b 吊销后完全拦截：读写都是 403 LICENSE_REQUIRED  -- GET=403 LICENSE_REQUIRED POST=403 LICENSE_REQUIRED
[PASS] 10c 吊销后原授权码无法再次激活  -- 403 LICENSE_REVOKED
[PASS] 11 服务端事件留痕  -- events=['issued', 'activated', 'device_bound', 'renewed', 'suspended', 'resumed', 'machine_mismatch', 'session_replaced', 'renewed', 'session_replaced', 'renewed', 'revoked']

通过 24 / 24
```

## 2 端到端（测试构建的桌面可执行文件，真实业务接口）

`~/.local/dongai-venv/bin/python scripts/license_e2e.py --exe desktop/dist/dongai-backend/dongai-backend --priv-key $S/priv.key`

（桌面模式下写操作还要账号 JWT，脚本在激活后注册登录；少一项「重启后仍只读」，因为桌面实例重启要拉 mongod，源码模式已覆盖。）

```
被测构建： {"test_build": true, "marker": "DONGAI-TEST-BUILD-7f3a", "kids": ["af8b6316"], "license_server": "http://127.0.0.1:18100", "app_version": "1.0.0+testbuild"}
license-server：http://127.0.0.1:18100  store=memory  kid=af8b6316
[PASS] 0a 未激活：status.state=unactivated  -- state=unactivated
[PASS] 0b 未激活：业务接口被完全拦截  -- 403 LICENSE_REQUIRED
[PASS] 1 客户端取机器码  -- machine_code=ANRF6-PABUV-4AEAK-BUBTM-GUSZG-QDCHS-4YILW-3DRT6-73
[PASS] 2 admin 签发授权码  -- lid=lic_8c52c26967e96d92 status=pending code前16位=PMRGIZLWL5WWC6BC…
[PASS] 3a 乱码授权码被拒  -- 400 LICENSE_INVALID
[PASS] 3b 激活成功  -- 200 state=valid plan=pro
[PASS] 3c 服务端：授权 active、绑定 1 台设备  -- status=active devices=1
[PASS] 4 续租成功，租约有效期向后推  -- 200 state=valid lease_exp 1794832649 -> 1794832653
[PASS] 5 业务接口可用（读和写都放行）  -- GET=200 POST=200
[PASS] 6a admin 停用授权  -- 200 suspended
[PASS] 6b 客户端续租被拒：LICENSE_SUSPENDED，state=suspended 且 readonly  -- 403 LICENSE_SUSPENDED state=suspended readonly=True
[PASS] 6c 只读降级：读 200，写 403 LICENSE_READONLY  -- GET=200 POST=403 LICENSE_READONLY
[PASS] 7 admin 恢复 -> 续租成功，写操作恢复  -- resume=200 renew=200 state=valid POST=200
[PASS] 8a 换机（授权码绑定的是另一台机器）：客户端拒绝激活  -- 403 LICENSE_MACHINE_MISMATCH state=unactivated biz=403
activate machine_mismatch lid=lic_8c52c26967e96d92
[PASS] 8b 服务端直接验证：同一授权码带别的机器分量激活被拒  -- 403 LICENSE_MACHINE_MISMATCH
[PASS] 9a 同机另一个实例用同一授权码激活（后激活者胜）  -- 200 state=valid
    （续租限频：等 27 秒）
[PASS] 9b 旧会话续租被拒 LICENSE_SESSION_CONFLICT，被完全拦截  -- renew=409 LICENSE_SESSION_CONFLICT state=session_conflict biz=403 LICENSE_REQUIRED
[PASS] 9c 旧会话重新激活后又换对方被顶掉（同一授权同时只有一个在线会话）  -- A activate=200 state=valid B renew=LICENSE_SESSION_CONFLICT
[PASS] 9d 服务端设备仍只有 1 台（两个实例同一机器分量）  -- devices=1
    （续租限频：等 15 秒）
[PASS] 10a admin 吊销 -> 续租被拒 LICENSE_REVOKED，state=revoked  -- revoke=200 renew=403 LICENSE_REVOKED state=revoked
[PASS] 10b 吊销后完全拦截：读写都是 403 LICENSE_REQUIRED  -- GET=403 LICENSE_REQUIRED POST=403 LICENSE_REQUIRED
[PASS] 10c 吊销后原授权码无法再次激活  -- 403 LICENSE_REVOKED
[PASS] 11 服务端事件留痕  -- events=['issued', 'activated', 'device_bound', 'renewed', 'suspended', 'resumed', 'machine_mismatch', 'session_replaced', 'renewed', 'session_replaced', 'renewed', 'revoked']

通过 23 / 23
```

降级结果与 `docs/license-client.md` 的表一致：停用 = 只读（读 200、写 403 `LICENSE_READONLY`，重启后仍然）；吊销、会话冲突、未激活、换机 = 完全拦截（403 `LICENSE_REQUIRED`）。

## 3 桌面冒烟测试

`~/.local/dongai-venv/bin/python desktop/smoke_test.py --priv-key $S/priv.key`（改前：桌面模式无法激活，9 个失败）

```
被测构建： {"test_build": true, "marker": "DONGAI-TEST-BUILD-7f3a", "kids": ["af8b6316"], "license_server": "http://127.0.0.1:18100", "app_version": "1.0.0+testbuild"}
license-server（内存仓库）：http://127.0.0.1:18100 kid=af8b6316
[PASS] 7 --selfcheck（Playwright 驱动） {"python": "3.12.10", "compiled": true, "ok": true, "ffmpeg": {"ok": true, "ffmpeg": {"path": "/opt/homebrew/bin/ffmpeg", "source": "p
[SKIP] 8 包内没有 ffmpeg（构建时未带 --ffmpeg-dir）
[PASS] 启动并打印 ready 行 {'port': 52171}
[PASS] 随包 mongod 已拉起 pid=[88925]
[PASS] mongod.pid 已写入 
[PASS] 1 /health 200 {'status': 'healthy', 'mongodb': 'connected', 'redis': 'disabled'}
[PASS] 2 不带令牌访问 /api/projects 为 401 got 401
[PASS] 2a 未激活时业务接口被拦截（403 LICENSE_REQUIRED） 403 {'code': 'LICENSE_REQUIRED', 'state': 'unactivated', 'message': '需要先激活授权后才能使用', 
[PASS] 2b 取机器码 ANRF6-PABUV-4AEAK-BUBTM-GUSZG-QDCHS-4YILW-3DRT6-73
[PASS] 2c 激活成功（测试公钥 + 本机 license-server） 200 state=valid storage=fallback
[PASS] 3a 注册 200
[PASS] 3b 登录 200
[PASS] 3c 创建项目 200
[PASS] 3d 列项目 [{'id': '6af9a775b8b509992f6c12ba', 'user_id': '6af9a775b8b509992f6c12b9', 'name': '冒烟项目', 'novel_content': None, 'genre
[PASS] 3e 替身 LLM（润色） {'code': 200, 'message': '润色完成', 'data': {'text': '（润色稿）暴雨演武场\n\n暴雨压在林家演武场上，青石板被砸得白茫茫一片。林风攥着扫帚站在场边，雨水顺着他的发梢往下淌。\n\n赵虎踩着积
[PASS] 3f 替身 LLM（提取资产，SSE） ars": 1157}

data: {"type": "done", "message": "提取完成：角色3、道具1、场景1", "data": {"characters": 3, "props": 1, "scenes": 1}}


[PASS] 3g 提取出角色 200 3
[PASS] 3h 替身文生图（需随包夹具、Pillow） 200 {'code': 200, 'message': '林风 参考图生成成功', 'data': {'img_path': 'images/b1e527d9-12c9-4293-876c-68ed12a50cf8.png', 'model': 'cogview-3-flash
[PASS] 3i 静态文件可取回 200 1487B
[PASS] 4a SIGTERM 后后端退出 rc=0
[PASS] 4b SIGTERM 后 mongod 消失 leftover=[]
[PASS] 4c mongod.pid 已清理 
[PASS] 5a 二次启动 ready（数据目录已有数据） 
[PASS] 5b kill -9 后端后 mongod 确实遗留（复现孤儿） orphan=[89076]
[PASS] 5c 再次启动成功 
[PASS] 5d 遗留 mongod 已被清理 old=[89076]
[PASS] 5e 现在只有一个新 mongod pids=[89089]
[PASS] 5f 重启后数据仍在（能用旧账号登录） 200
[PASS] 5g 重启后项目仍在 
[PASS] 5h 清除本机授权（deactivate） 200 {'state': 'unactivated', 'plan': None, 'features': [], 'expires_at': None, 'grac
[PASS] 6 SIGINT 后后端和 mongod 都消失 rc=0

== 指标 ==
包体积（du -sh）: 433M
冷启动到 ready（秒）: 8.9
内存：后端进程 RSS（MB）: 155
内存：mongod RSS（MB）: 88
二次（热）启动到 ready（秒）: 1.1

通过 30 / 30
```

激活后 `storage=fallback`：冒烟脚本把子进程的 HOME 指向临时目录，macOS 钥匙串不可用，走了降级存储（见 `docs/license-client.md`「存储加固」）。好处是不会往真实钥匙串写条目；代价是**钥匙串路径（secure 模式）没有在本次验收里覆盖**，它另有 `check_keystore.py` 和单测。结束时 `deactivate` 也清除了存储。

## 4 单元测试（无回归）

```
backend:        11 failed, 380 passed, 66 skipped   （11 个失败与基线一致，均为 test_character_forms/test_director_prompt/test_scene_views/test_script/test_segments/test_shot_split 的既有失败）
license:        62 passed
license-server: 131 passed, 15 skipped
backend/tests/test_license_test_build.py（新增）: 2 passed
```

## 没跑成 / 没覆盖的

- **Windows**：没有 Windows 环境。`build_backend.py` 的 Windows 分支、`smoke_test.py`（POSIX 版）、`license_e2e.py`（用了 `os.killpg`、SIGTERM）都未在 Windows 实测；Windows 钥匙串（凭据管理器）、`check_release_build.py` 的 `.exe` 路径同样未测。
- **真实证书/公证**：没有 Apple Developer ID 与 Windows EV 证书，签名、公证产物没验；本次测的是未签名的测试构建。
- **正式公钥、正式授权服务地址**：仍是占位（`core/license_keys.py`、`core/license_config.py`），发版前替换；`check_release_build.py` 对占位地址只提醒不判失败。
- **钥匙串 secure 模式**的桌面端到端：见上，本次走 fallback。
- **时间类场景**（租约过期/宽限/时钟回拨）没有在 e2e 里重跑，沿用 `test_license_renew.py` 的注入时钟单测。
- 授权服务只验了内存仓库和本机临时 mongod，未验生产部署（HTTPS、反代、真实 IP 限频）。
