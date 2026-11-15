# 测试 dmg（testbuild）：管理端签发 → 客户端激活 体验手册

这是用「固定测试密钥」构建的 DongAI 桌面包，只用于本机体验授权流程，**不得分发或发布**（启动有测试构建警告，版本带 `+testbuild`）。

## 产物

- dmg：`/Users/wangmaolin/IdeaProjects/dong-ai-manju-wt-testdmg/desktop/shell/out/DongAI-0.1.0-testbuild-arm64.dmg`（macOS arm64，未签名，首次打开请右键「打开」或在「隐私与安全性」里放行）
- 同内容的未打包 app：`.../desktop/shell/out/mac-arm64/DongAI.app`
- 后端包：`.../desktop/dist/dongai-backend`（`--build-info` 可看到 test_build=true、kid=8c66a17b、授权服务 `http://127.0.0.1:18100`）
- 测试密钥（仓库外，权限 600）：`~/.local/dongai-test-license/signing.key`（私钥）、`signing.pub`（公钥，kid `8c66a17b`）

客户端写死的授权服务地址是 `http://127.0.0.1:18100`，所以演示授权服务必须监听这个端口。

## 1. 启动演示授权服务（固定私钥）

先停掉旧的演示服务（旧的是随机私钥，签的码新包认不了），再：

```bash
cd /Users/wangmaolin/IdeaProjects/dong-ai-manju-wt-testdmg
E2E_ADMIN_PASSWORD='你自己定一个12位以上的密码' scripts/run_demo_license_server.sh
```

- 监听 `127.0.0.1:18100`；改端口：脚本第一个参数或 `E2E_LICENSE_PORT`（但测试包只连 18100）。
- 内置 3 个演示管理员，密码都是上面的 `E2E_ADMIN_PASSWORD`：`e2e_super`（超管）、`e2e_ops`（运营，可签发）、`e2e_readonly`（只读）。
- **内存仓库：服务重启后所有已签发的授权、事件都会丢失**。客户端本机已激活的授权会在下次续租时被服务端判无效，重启后需要重新签发并重新激活。私钥是固定的，所以重启前签的码仍能通过签名校验，但服务端已不认。
- 管理端前端（license-admin）照常连 18100 即可。

## 2. 管理端签发授权码

1. 打开管理端，用 `e2e_ops` 或 `e2e_super` 登录。
2. 客户端先拿到机器码（见下一节第 2 步），在管理端「签发授权」里填：机器码、套餐、功能点、到期时间，提交。
3. 复制生成的授权码。

## 3. 客户端激活

1. 双击 dmg，把 DongAI 拖到「应用程序」（或直接运行 `mac-arm64/DongAI.app`），启动。
2. 看到激活页后，点「复制机器码」，发给管理端。
3. 把管理端签发的授权码粘贴到激活页，提交；成功后进入注册/登录页，业务接口可用。

## 4. 重置客户端（会清空本地数据）

> 下面会删除本机 DongAI 的全部本地数据（项目、账号、素材、日志、授权），不可恢复。
> 注意：如果同时装着旧的 L-06 DongAI.app，它和测试包共用同一个数据目录，重置会影响它。

1. 退出 DongAI（Cmd+Q）。
2. `rm -rf ~/Library/Application\ Support/DongAI`
3. 钥匙串里的授权数据密钥：打开「钥匙串访问」搜索 `DongAI` 删除，或 `security delete-generic-password -s DongAI`（可能需多次，直到提示找不到）。
4. 重新启动即回到未激活状态。

只想「取消激活」而保留数据：在应用里取消激活，或请求 `POST /api/license/deactivate`。

## 5. 复现构建

```bash
cd /Users/wangmaolin/IdeaProjects/dong-ai-manju-wt-testdmg
export DONGAI_MONGOD_BIN=~/.local/dongai-spike/bin-arm64/mongodb-macos-aarch64-7.0.48/bin/mongod
(cd frontend && npm run build)
~/.local/dongai-venv/bin/python desktop/build_backend.py --no-fixtures \
  --test-public-key ~/.local/dongai-test-license/signing.pub \
  --test-license-server http://127.0.0.1:18100
~/.local/dongai-venv/bin/python desktop/check_release_build.py --expect-test
cd desktop/shell
C=~/.local/dongai-build   # 避开 ~/.npm 里 root 属主文件
NPM_CONFIG_CACHE=$C/npm-cache ELECTRON_CACHE=$C/electron-cache ELECTRON_BUILDER_CACHE=$C/electron-builder-cache \
CSC_IDENTITY_AUTO_DISCOVERY=false npx electron-builder --mac dmg --arm64 -c.extraMetadata.version=0.1.0-testbuild
```

构建期间不要同时从源码跑后端测试（`backend/core/_test_build.py` 是临时生成的）。

## 6. 已做的验证

`check_release_build.py --expect-test` 通过；用新包后端在临时数据目录里，经临时端口 18199 的演示服务（固定私钥）完成：签发 → 激活（state=valid, plan=pro）→ 注册/登录/建项目/列项目；结束后已取消激活并清理进程。
