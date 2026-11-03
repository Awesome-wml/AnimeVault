# 豆包视频批量生成配置指南

## 功能说明

本系统支持通过浏览器自动化批量生成豆包视频，核心特性：

1. **多账号池管理**：维护多个豆包账号，自动轮询使用
2. **每日配额控制**：每个账号每天限制5条，自动跟踪使用情况
3. **智能任务分配**：12条分镜自动分配到多个账号
4. **失败重试**：支持单条重新生成，不增加配额计数
5. **登录态保持**：接管浏览器已登录状态，无需重复登录

## 配置步骤

### 1. 安装 Playwright

在后端容器或本地环境中安装：

```bash
cd backend
pip install playwright==1.40.0
playwright install chromium
```

### 2. 配置豆包账号池

编辑 `doubao_accounts.json` 文件（首次运行会自动创建）：

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
    },
    {
      "id": "account_2",
      "name": "豆包账号2",
      "profile_dir": ".doubao_profiles/account_2",
      "enabled": true,
      "usage": {
        "date": "2026-11-03",
        "count": 0
      }
    },
    {
      "id": "account_3",
      "name": "豆包账号3",
      "profile_dir": ".doubao_profiles/account_3",
      "enabled": true,
      "usage": {
        "date": "2026-11-03",
        "count": 0
      }
    }
  ],
  "notes": "profile_dir 是相对于项目根目录的 Chrome Profile 路径，每个账号需要独立登录一次"
}
```

**配置说明**：
- `id`: 账号唯一标识
- `name`: 账号名称（用于显示）
- `profile_dir`: Chrome Profile 目录路径（相对项目根目录）
- `enabled`: 是否启用该账号
- `usage`: 自动维护的使用记录

### 3. 初始化账号登录态

每个账号需要**手动登录一次**豆包，之后会自动保持登录态。

运行以下脚本为每个账号初始化：

```python
# init_doubao_accounts.py
from playwright.sync_api import sync_playwright
import time

def init_account(profile_dir):
    """手动登录豆包账号并保存登录态"""
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            profile_dir,
            channel="chrome",
            headless=False
        )
        page = context.pages[0] if context.pages else context.new_page()
        
        # 访问豆包
        page.goto("https://www.doubao.com/chat")
        
        print(f"请在浏览器中登录豆包账号...")
        print("登录完成后，按回车继续...")
        input()
        
        # 验证登录
        if page.locator("[contenteditable=true]").count() > 0:
            print(f"✅ 账号登录成功，登录态已保存到 {profile_dir}")
        else:
            print(f"❌ 登录失败，请重试")
        
        context.close()

# 初始化所有账号
init_account(".doubao_profiles/account_1")
init_account(".doubao_profiles/account_2")
init_account(".doubao_profiles/account_3")
```

### 4. 使用系统

#### 前端操作

1. 进入分镜工作台页面
2. 确保所有分镜已完成（提示词、图片、音频等）
3. 点击"批量生成视频"按钮
4. 查看账号配额状态
5. 点击"开始生成"

#### 后端 API

**查看账号状态**：
```bash
GET /api/video/accounts/status
```

返回示例：
```json
{
  "data": {
    "accounts": [
      {
        "id": "account_1",
        "name": "豆包账号1",
        "today_used": 2,
        "daily_limit": 5,
        "available": true,
        "remaining": 3
      }
    ],
    "total_available_quota": 13
  }
}
```

**批量生成视频**：
```bash
POST /api/video/generate/batch?project_id=xxx
```

**单条重新生成**：
```bash
POST /api/video/generate/single?shot_id=xxx&account_id=account_1
```

## 工作原理

### 任务分配逻辑

假设有 12 条分镜，3 个账号：

1. **账号1**（可用3条）：分配分镜 1-3
2. **账号2**（可用5条）：分配分镜 4-8
3. **账号3**（可用5条）：分配分镜 9-12（共4条）

分配完成后，系统会：
- 自动更新每个账号的使用计数
- 第二天自动重置计数
- 失败的分镜可单独重新生成

### 浏览器自动化流程

对于每个分镜：

1. 连接到账号的 Chrome Profile
2. 验证登录状态
3. 上传图片和音频资产
4. 填写视频生成提示词
5. 发送请求
6. 等待间隔（避免频繁请求）

## 常见问题

### Q: 账号登录失效怎么办？

A: 重新运行初始化脚本为该账号登录即可，登录态会自动保存。

### Q: 如何增加更多账号？

A: 在 `doubao_accounts.json` 中添加新账号配置，然后运行初始化脚本登录。

### Q: 每天的配额会自动重置吗？

A: 是的，系统会在每天0点自动重置所有账号的使用计数。

### Q: 生成失败如何重试？

A: 在分镜表格中点击"重新生成"按钮，会自动选择可用账号重新生成，失败不计入配额。

### Q: Chrome Profile 目录在哪里？

A: 相对于项目根目录，例如 `.doubao_profiles/account_1/` 会创建在项目根目录下。

### Q: 可以在 Docker 中运行吗？

A: 可以，但需要安装 Chrome 浏览器。建议在宿主机运行自动化脚本，或使用支持浏览器的 Docker 镜像。

## 安全建议

1. **不要提交 Profile 目录**：已添加到 `.gitignore`
2. **不要分享账号配置**：包含敏感信息
3. **定期更换密码**：保持账号安全
4. **监控异常登录**：及时发现账号被盗用

## 维护和监控

系统会自动记录日志到控制台，包括：
- 账号使用情况
- 任务分配详情
- 生成成功/失败统计
- 错误和异常信息

建议定期检查日志，确保系统正常运行。
