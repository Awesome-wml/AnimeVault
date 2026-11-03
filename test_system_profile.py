#!/usr/bin/env python3
"""测试 Chrome System Profile"""
import subprocess
from pathlib import Path
from playwright.sync_api import sync_playwright
import time

SYSTEM_PROFILE = Path.home() / "Library/Application Support/Google/Chrome/System Profile"

print("=" * 60)
print("测试 Chrome System Profile")
print("=" * 60)
print(f"路径: {SYSTEM_PROFILE}")
print()

# 检查 Chrome
result = subprocess.run(["pgrep", "-x", "Google Chrome"], capture_output=True)
if result.returncode == 0:
    print("⚠️  请先关闭 Chrome，等待 3 秒...")
    time.sleep(3)

print("启动浏览器...")

with sync_playwright() as p:
    context = p.chromium.launch_persistent_context(
        str(SYSTEM_PROFILE),
        channel="chrome",
        headless=False,
        args=["--disable-blink-features=AutomationControlled"],
    )
    
    page = context.pages[0] if context.pages else context.new_page()
    
    print("访问豆包...")
    page.goto("https://www.doubao.com/chat")
    time.sleep(3)
    
    editor = page.locator("[contenteditable=true]").count()
    login = page.get_by_text("登录", exact=True).count()
    
    print()
    if editor > 0:
        print("✅ System Profile 已登录豆包！")
    elif login > 0:
        print("❌ System Profile 未登录")
    else:
        print("⚠️  状态不确定，请查看浏览器")
    
    print("\n保持打开 15 秒...")
    for i in range(15, 0, -1):
        print(f"\r{i}秒...", end="", flush=True)
        time.sleep(1)
    
    print("\n关闭...")
    context.close()
