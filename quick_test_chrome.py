#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
快速测试：连接到 Chrome Default Profile
"""
import os
import subprocess
from pathlib import Path
from playwright.sync_api import sync_playwright
import time

# macOS Chrome Default Profile
CHROME_DEFAULT_PROFILE = Path.home() / "Library/Application Support/Google/Chrome/Default"

print()
print("=" * 60)
print("快速测试：连接现有 Chrome Profile")
print("=" * 60)
print(f"Profile: {CHROME_DEFAULT_PROFILE}")
print()

# 检查 Chrome 是否正在运行
print("1. 检查 Chrome 进程...")
result = subprocess.run(["pgrep", "-x", "Google Chrome"], capture_output=True)
if result.returncode == 0:
    print("   ⚠️  Chrome 正在运行")
    print("   为了避免冲突，需要先关闭 Chrome")
    print()
    print("   关闭 Chrome 后，脚本会在 3 秒后自动继续...")
    
    # 等待用户关闭
    for i in range(3, 0, -1):
        time.sleep(1)
        print(f"   {i}...")
    print()
else:
    print("   ✅ Chrome 未运行")
    print()

print("2. 启动 Playwright Chrome...")

with sync_playwright() as p:
    try:
        context = p.chromium.launch_persistent_context(
            str(CHROME_DEFAULT_PROFILE),
            channel="chrome",
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
            viewport={"width": 1280, "height": 800},
        )
        
        page = context.pages[0] if context.pages else context.new_page()
        
        print("   ✅ 浏览器已启动")
        print()
        
        print("3. 访问豆包网站...")
        page.goto("https://www.doubao.com/chat", timeout=30000)
        
        print("   ✅ 页面加载完成")
        print()
        
        time.sleep(2)
        
        print("4. 检查登录状态...")
        
        # 检查输入框（已登录）
        editor_count = page.locator("[contenteditable=true]").count()
        # 检查登录按钮（未登录）
        login_btn_count = page.get_by_text("登录", exact=True).count()
        
        print()
        print("=" * 60)
        print("测试结果")
        print("=" * 60)
        
        if editor_count > 0:
            print("✅ 状态: 已登录")
            print(f"   找到 {editor_count} 个输入框（contenteditable）")
            print()
            print("🎉 成功！可以接管浏览器的登录状态")
        elif login_btn_count > 0:
            print("❌ 状态: 未登录")
            print(f"   找到 {login_btn_count} 个登录按钮")
            print()
            print("💡 提示:")
            print("   该 Profile 中可能没有登录豆包")
            print("   或者使用了不同的 Chrome Profile")
        else:
            print("⚠️  状态: 不确定")
            print("   请查看浏览器窗口")
        
        print("=" * 60)
        print()
        print("浏览器将保持打开 20 秒...")
        
        for i in range(20, 0, -1):
            print(f"\r倒计时: {i} 秒...  ", end="", flush=True)
            time.sleep(1)
        
        print("\n")
        print("5. 关闭浏览器...")
        context.close()
        
        print("✅ 测试完成！")
        
    except Exception as e:
        print(f"\n❌ 错误: {e}")
        import traceback
        traceback.print_exc()

print()
