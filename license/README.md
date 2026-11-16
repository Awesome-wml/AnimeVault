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

## 租约 payload（格式版本 v=2）

| 字段 | 类型 | 含义 |
|---|---|---|
| `typ` / `v` / `kid` | str / int(=2) / str | 类型 `lease`、格式版本、签名密钥 |
| `lid` / `sid` / `mc` | str / str / list[str] | 授权 ID、会话 ID、机器码分量 |
| `iat` / `exp` | int | 签发时间、租约过期时间（= iat + ttl，不超过 `lexp`） |
| `st` | str | 状态，目前恒为 `active` |
| `lexp` | int | **授权到期时间**（Unix 秒），客户端判断授权是否到期以它为准 |
| `plan` | str | 套餐 |
| `features` | list[str] | 功能点 |
| `cv` | int | 授权码版本（code_version，管理员延期/重签时递增，仅用于诊断） |

> **破坏性变更**：租约格式版本由 1 升到 2，`lexp/plan/features/cv` 均为**必需**字段并在签名内。
> `verify_lease` 对 v=1 的旧租约返回 `LicenseInvalid`（尚无已发布版本，不做兼容；客户端需联网重新激活）。
> 授权码（`typ=license`）仍是 `v=1`，格式不变。
> 租约响应 JSON 里的 `license.*` 展示字段不在签名内，不可信，决策一律以租约 payload 为准。

## 测试

```
cd license && PYTHONPATH=. python -m pytest tests -q
```
