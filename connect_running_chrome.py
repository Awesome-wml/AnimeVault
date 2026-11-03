#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
连接到正在运行的 Chrome（通过 CDP）
这样可以直接使用你已经登录的浏览器
"""
from playwright.sync_api import sync_playwright
import time

print()
print("=" * 60)
print("连接到正在运行的 Chrome")
print("=" * 60)
print()
print("步骤1: 启动 Chrome 时需要开启调试端口")
print()
print("请执行以下命令启动 Chrome:")
print()
print("  /Applications/Google\\ Chrome.app/Contents/MacOS/Google\\ Chrome \\")
print("    --remote-debugging-port=9222 \\")
print("    --user-data-dir=\"$HOME/Library/Application Support/Google/Chrome\"")
print()
print("或者使用快捷命令（保存为 start_chrome_debug.sh）:")
print()
print("  open -a 'Google Chrome' --args --remote-debugging-port=9222")
print()
print("-" * 60)
input("启动完成后，按回车继续...")
print()

print("步骤2: 连接到 Chrome...")

with sync_playwright() as p:
    try:
        # 连接到调试端口
        browser = p.chromium.connect_over_cdp("http://localhost:9222")
        
        print("✅ 已连接到 Chrome")
        print()
        
        # 获取所有上下文（浏览器窗口）
        contexts = browser.contexts
        print(f"找到 {len(contexts)} 个浏览器上下文")
        
        if not contexts:
            print("❌ 没有找到打开的浏览器窗口")
            print("   请先在 Chrome 中打开一个窗口")
            browser.close()
            exit(1)
        
        # 使用第一个上下文
        context = contexts[0]
        pages = context.pages
        
        print(f"找到 {len(pages)} 个标签页")
        
        # 创建新标签页或使用现有标签
        if pages:
            page = pages[0]
        else:
            page = context.new_page()
        
        print()
        print("步骤3: 访问豆包...")
        page.goto("https://www.doubao.com/chat", timeout=30000)
        time.sleep(3)
        
        print()
        print("步骤4: 检查登录状态...")
        
        editor = page.locator("[contenteditable=true]").count()
        login_btn = page.get_by_text("登录", exact=True).count()
        
        print()
        if editor > 0:
            print("✅ 已登录！找到输入框")
            print()
            print("🎉 成功！可以使用这个方式控制已登录的浏览器")
            
            # 测试发送消息
            print()
            test = input("是否测试发送消息? (y/n): ").strip().lower()
            
            if test == 'y':
                print()
                print("发送测试消息...")
                
                editor_elem = page.locator("[contenteditable=true]").first
                editor_elem.click()
                time.sleep(0.5)
                
                test_msg = "测试：请回复'ok'"
                page.evaluate(f"""() => {{
                    const ed = document.querySelector('[contenteditable=true]');
                    if (ed) {{
                        ed.focus();
                        document.execCommand('insertText', false, '{test_msg}');
                    }}
                }}""")
                
                time.sleep(1)
                editor_elem.press("Enter")
                
                print("✅ 消息已发送")
                print()
                print("等待 15 秒，查看回复...")
                
                for i in range(15, 0, -1):
                    print(f"\r{i}秒...", end="", flush=True)
                    time.sleep(1)
                
                print("\n")
        
        elif login_btn > 0:
            print("❌ 未登录，发现登录按钮")
            print("   请先在这个 Chrome 窗口中登录豆包")
        else:
            print("⚠️  状态不确定")
        
        print()
        print("浏览器保持打开，你可以继续使用")
        print("脚本将在 10 秒后断开连接（不会关闭浏览器）")
        
        for i in range(10, 0, -1):
            print(f"\r{i}秒...", end="", flush=True)
            time.sleep(1)
        
        print("\n")
        print("断开连接...")
        browser.close()
        
        print("✅ 完成！")
        
    except Exception as e:
        print(f"❌ 连接失败: {e}")
        print()
        print("请确保:")
        print("  1. Chrome 已经以调试模式启动")
        print("  2. 调试端口是 9222")
        print("  3. 没有其他程序占用该端口")

print()
