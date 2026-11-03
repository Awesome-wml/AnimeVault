# 豆包自动化解决方案

## 问题分析

经过测试发现：
1. ✅ Playwright 可以正常工作
2. ✅ 可以打开浏览器并访问豆包
3. ❌ 无法接管你现有浏览器的登录状态

**根本原因**：
- 使用 `launch_persistent_context` 时会创建独立的浏览器实例
- 即使指定了相同的 Profile 目录，也不会共享Cookie/登录状态
- Chrome 的登录状态可能与特定的浏览器会话绑定

## 推荐方案

### 方案1：在自动化浏览器中手动登录一次（推荐）

这是最简单可靠的方案：

1. 运行初始化脚本，让浏览器打开豆包
2. **手动登录一次**（输入手机号+验证码）
3. 登录状态会自动保存
4. 后续所有自动化都能使用这个登录状态

**操作步骤**：

```bash
python3 init_account_simple.py
```

脚本会：
- 打开浏览器
- 访问豆包
- 等待你手动登录
- 登录完成后，状态自动保存

### 方案2：使用多个独立账号

如果你有多个豆包账号：

1. 为每个账号创建独立的 Profile
2. 每个账号登录一次
3. 配置账号池

```json
{
  "accounts": [
    {
      "id": "account_1",
      "profile_dir": ".doubao_profiles/account_1",
      "name": "豆包账号1"
    },
    {
      "id": "account_2",
      "profile_dir": ".doubao_profiles/account_2",
      "name": "豆包账号2"
    }
  ]
}
```

### 方案3：Cookies 同步（复杂）

从你的浏览器导出 Cookies，导入到自动化浏览器（不推荐，容易失效）

## 建议流程

### 第一步：初始化账号登录

```bash
# 运行初始化脚本
python3 init_account_simple.py
```

### 第二步：测试登录状态

```bash
# 测试账号是否已登录
python3 test_browser_login.py
```

### 第三步：测试发送消息

```bash
# 测试完整流程
python3 test_send_message.py
```

### 第四步：配置账号池

编辑 `doubao_accounts.json`：

```json
{
  "accounts": [
    {
      "id": "account_1",
      "name": "豆包账号1",
      "profile_dir": ".doubao_profiles/account_1",
      "enabled": true,
      "usage": {
        "date": "2026-11-03",
        "count": 0
      }
    }
  ]
}
```

### 第五步：开始使用

在前端页面点击"批量生成视频"即可！

## 常见问题

### Q: 为什么不能直接用我现有的登录状态？

A: 浏览器的登录状态与特定的浏览器进程绑定，Playwright 创建的是新进程。

### Q: 每次都要登录吗？

A: 不需要！登录一次后，状态会永久保存在 Profile 目录中。

### Q: 多个账号怎么管理？

A: 为每个账号创建独立的 Profile，初始化时分别登录一次。

### Q: 登录状态会过期吗？

A: 可能会，但通常很久才过期。过期后重新登录一次即可。

## 下一步

我会创建一个简单的初始化脚本，让你轻松完成首次登录！
