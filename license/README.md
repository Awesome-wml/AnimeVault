# dongai_license

授权码与在线租约的签名/验证库（Ed25519），设计见 `docs/license-design.md`。

## 密钥保管

- **私钥只放授权服务器**：环境变量或密钥管理服务。绝不进入客户端安装包和代码仓库。
- **公钥内置客户端**，以 `kid -> 公钥` 字典形式提供，用于离线验证授权码和租约。
- 生成：`python scripts/gen_keys.py --out ~/secure/license_priv.key`。
  脚本只把私钥写入指定文件（权限 600），检测到路径在 git 仓库内会拒绝；屏幕只打印 kid 和公钥。

## kid 轮换

1. 生成新密钥对，得到新 kid；服务器改用新私钥签发，payload 中写新 kid。
2. 发布新版客户端，公钥字典同时包含新旧 kid（客户端支持多公钥，按 payload 中的 kid 选公钥）。
3. 旧授权/租约仍由旧 kid 验证，直到自然过期或被重签；确认旧版本退出后，从字典移除旧公钥。
4. 私钥泄露时：立即停用旧 kid，发布只含新公钥的版本并强制升级，旧 kid 签的授权随之作废。

## 测试

```
cd license && PYTHONPATH=. python -m pytest tests -q
```
