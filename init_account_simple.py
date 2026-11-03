#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
简单的账号初始化脚本
打开浏览器，让你手动登录豆包，登录状态会自动保存
"""
from pathlib import Path
from playwright.sync_api import sync_playwright
import time

PROJECT_ROOT = Path(__file__).parent
PROFILE_DIR = PROJECT_ROOT / ".doubao_profiles" / "account_1"

print()
print("=" * 60)
print("豆包账号初始化")
print("=" * 60)
print()
print(f"Profile 目录: {PROFILE_DIR}")
print()
print("这个脚本会:")
print("  1. 打开一个新的 Chrome 浏览器")
print("  2. 访问豆包网站")
print("  3. 等待你手动登录（输入手机号+验证码）")
print("  4. 登录完成后，状态会自动保存")
print("  5. 以后运行自动化时，不需要再登录")
print()
input("按回车开始...")
print()

PROFILE_DIR.mkdir(parents=True, exist_ok=True)

with sync_playwright() as p:
    print("1. 启动浏览器...")
    
    context = p.chromium.launch_persistent_context(
        str(PROFILE_DIR),
        channel="chrome",
        headless=False,
        args=["--disable-blink-features=AutomationControlled"],
        viewport={"width": 1280, "height": 800},
    )
    
    page = context.pages[0] if context.pages else context.new_page()
    
    print("2. 访问豆包...")
    page.goto("https://www.doubao.com/chat", timeout=30000)
    
    time.sleep(3)
    
    # 检查登录状态
    editor_count = page.locator("[contenteditable=true]").count()
    
    if editor_count > 0:
        print()
        print("✅ 检测到已经登录！")
        print("   登录状态已保存，可以直接使用")
    else:
        print()
        print("⚠️  检测到未登录")
        print()
        print("=" * 60)
        print("请在浏览器中完成以下操作:")
        print("=" * 60)
        print()
        print("  1. 点击【登录】按钮")
        print("  2. 选择【手机号登录】")
        print("  3. 输入手机号")
        print("  4. 点击【获取验证码】")
        print("  5. 输入短信验证码")
        print("  6. 点击【登录】")
        print()
        print("=" * 60)
        print()
        input("登录完成后，按回车继续...")
        
        # 再次检查
        time.sleep(1)
        editor_count = page.locator("[contenteditable=true]").count()
        
        if editor_count > 0:
            print()
            print("✅ 登录成功！")
            print(f"   登录状态已保存到: {PROFILE_DIR}")
        else:
            print()
            print("⚠️  仍未检测到登录")
            print("   请检查是否真的登录成功")
    
    print()
    print("3. 测试发送消息...")
    print()
    test = input("是否测试发送一条消息？(y/n): ").strip().lower()
    
    if test == 'y':
        try:
            editor = page.locator("[contenteditable=true]").first
            editor.click()
            time.sleep(0.5)
            
            test_msg = "测试消息：1+1=?"
            print(f"   发送: {test_msg}")
            
            page.evaluate(f"""() => {{
                const ed = document.querySelector('[contenteditable=true]');
                if (ed) {{
                    ed.focus();
                    document.execCommand('insertText', false, '{test_msg}');
                }}
            }}""")
            
            time.sleep(1)
            editor.press("Enter")
            
            print("   ✅ 消息已发送")
            print()
            print("   等待 10 秒，查看豆包回复...")
            
            for i in range(10, 0, -1):
                print(f"\r   {i} 秒...", end="", flush=True)
                time.sleep(1)
            
            print("\n")
        except Exception as e:
            print(f"   ❌ 测试失败: {e}")
    
    print()
    print("4. 保持浏览器打开 10 秒...")
    print("   （你可以继续使用浏览器）")
    
    for i in range(10, 0, -1):
        print(f"\r   {i} 秒...", end="", flush=True)
        time.sleep(1)
    
    print("\n")
    print("5. 关闭浏览器...")
    context.close()
    
    print()
    print("=" * 60)
    print("✅ 初始化完成！")
    print("=" * 60)
    print()
    print(f"登录状态已保存在: {PROFILE_DIR}")
    print()
    print("下一步:")
    print("  1. 运行 python3 test_browser_login.py 验证登录")
    print("  2. 在前端页面使用批量生成视频功能")
    print()

print()
