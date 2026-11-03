#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试发送消息到豆包
验证完整的自动化流程
"""
import subprocess
from pathlib import Path
from playwright.sync_api import sync_playwright
import time

CHROME_DEFAULT = Path.home() / "Library/Application Support/Google/Chrome/Default"

print()
print("=" * 60)
print("测试豆包消息发送")
print("=" * 60)
print()

# 检查 Chrome
result = subprocess.run(["pgrep", "-x", "Google Chrome"], capture_output=True)
if result.returncode == 0:
    print("⚠️  请先关闭所有 Chrome 窗口")
    print("等待 5 秒...")
    for i in range(5, 0, -1):
        print(f"{i}...", end=" ", flush=True)
        time.sleep(1)
    print("\n")

print("1. 启动浏览器...")

with sync_playwright() as p:
    context = p.chromium.launch_persistent_context(
        str(CHROME_DEFAULT),
        channel="chrome",
        headless=False,
        args=["--disable-blink-features=AutomationControlled"],
        viewport={"width": 1280, "height": 800},
    )
    
    page = context.pages[0] if context.pages else context.new_page()
    page.set_default_timeout(15000)
    
    print("2. 访问豆包...")
    page.goto("https://www.doubao.com/chat", timeout=30000)
    time.sleep(3)
    
    print("3. 检查登录状态...")
    
    # 检查输入框
    editor = page.locator("[contenteditable=true]").first
    if editor.count() == 0:
        print("❌ 未找到输入框，可能未登录")
        context.close()
        exit(1)
    
    print("   ✅ 已登录（找到输入框）")
    
    # 测试消息
    test_message = "测试：1+1等于几？（这是自动化测试消息）"
    
    print(f"\n4. 发送测试消息: {test_message}")
    
    # 点击输入框
    editor.click()
    time.sleep(0.5)
    
    # 输入文本
    print("   - 输入文本...")
    page.evaluate(f"""() => {{
        const editor = document.querySelector('[contenteditable=true]');
        if (editor) {{
            editor.focus();
            document.execCommand('insertText', false, '{test_message}');
        }}
    }}""")
    
    time.sleep(1)
    
    # 发送（按回车）
    print("   - 发送消息...")
    editor.press("Enter")
    time.sleep(1)
    
    # 兜底：点击发送按钮
    try:
        page.evaluate("""() => {
            const buttons = document.querySelectorAll('button');
            for (const btn of buttons) {
                const text = (btn.textContent || '').trim();
                if (text === '发送' || text === '↑') {
                    btn.click();
                    break;
                }
            }
        }""")
    except:
        pass
    
    print("   ✅ 消息已发送！")
    
    print("\n5. 等待回复...")
    print("   （浏览器将保持打开 20 秒，你可以查看豆包的回复）\n")
    
    for i in range(20, 0, -1):
        print(f"\r   倒计时: {i} 秒...  ", end="", flush=True)
        time.sleep(1)
    
    print("\n\n6. 关闭浏览器...")
    context.close()
    
    print("\n" + "=" * 60)
    print("✅ 测试完成！")
    print("=" * 60)
    print()
    print("如果你看到豆包回复了测试消息，说明自动化完全成功！")
    print()
