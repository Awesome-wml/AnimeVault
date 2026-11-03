#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
使用你已经打开的豆包标签页
不创建新标签，直接控制现有的登录页面
"""
from playwright.sync_api import sync_playwright
import time

print()
print("=" * 60)
print("连接到已打开的豆包标签页")
print("=" * 60)
print()
print("请确保:")
print("  1. Chrome 已经以调试模式运行（刚才已启动）")
print("  2. 你已经在 Chrome 中打开了豆包网站并登录")
print("  3. 豆包标签页保持打开状态")
print()
input("准备好了按回车继续...")
print()

with sync_playwright() as p:
    try:
        print("1. 连接到 Chrome...")
        browser = p.chromium.connect_over_cdp("http://localhost:9222")
        print("   ✅ 已连接")
        
        contexts = browser.contexts
        if not contexts:
            print("❌ 没有找到浏览器上下文")
            browser.close()
            exit(1)
        
        context = contexts[0]
        pages = context.pages
        
        print(f"\n2. 查找豆包标签页（共 {len(pages)} 个标签）...")
        
        # 查找已经打开的豆包页面
        doubao_page = None
        for page in pages:
            url = page.url
            print(f"   - {url}")
            if "doubao.com" in url:
                doubao_page = page
                print(f"     ✅ 找到豆包页面！")
                break
        
        if not doubao_page:
            print("\n❌ 没有找到打开的豆包标签页")
            print("   请先在 Chrome 中打开 https://www.doubao.com/chat")
            browser.close()
            exit(1)
        
        print(f"\n3. 使用找到的豆包标签页")
        print(f"   URL: {doubao_page.url}")
        
        # 确保页面在前台
        doubao_page.bring_to_front()
        time.sleep(1)
        
        print("\n4. 检查登录状态...")
        
        editor_count = doubao_page.locator("[contenteditable=true]").count()
        login_btn_count = doubao_page.get_by_text("登录", exact=True).count()
        
        print()
        if editor_count > 0:
            print("✅ 已登录！找到输入框")
            print()
            print("=" * 60)
            print("成功！现在可以控制这个已登录的标签页")
            print("=" * 60)
            
            # 测试发送消息
            print()
            test = input("\n是否测试发送一条消息? (y/n): ").strip().lower()
            
            if test == 'y':
                print()
                print("5. 发送测试消息...")
                
                editor = doubao_page.locator("[contenteditable=true]").first
                editor.click()
                time.sleep(0.5)
                
                test_msg = "你好，这是自动化测试消息"
                print(f"   消息内容: {test_msg}")
                
                doubao_page.evaluate(f"""() => {{
                    const ed = document.querySelector('[contenteditable=true]');
                    if (ed) {{
                        ed.focus();
                        document.execCommand('insertText', false, '{test_msg}');
                    }}
                }}""")
                
                time.sleep(1)
                
                # 发送
                print("   发送中...")
                editor.press("Enter")
                time.sleep(1)
                
                # 兜底：点击发送按钮
                try:
                    doubao_page.evaluate("""() => {
                        const btns = document.querySelectorAll('button');
                        for (const btn of btns) {
                            const txt = (btn.textContent || '').trim();
                            if (txt === '发送' || txt === '↑') {
                                btn.click();
                                break;
                            }
                        }
                    }""")
                except:
                    pass
                
                print("   ✅ 消息已发送！")
                print()
                print("   等待 15 秒查看回复...")
                
                for i in range(15, 0, -1):
                    print(f"\r   {i} 秒...", end="", flush=True)
                    time.sleep(1)
                
                print("\n")
                print("   查看一下豆包是否回复了？")
        
        elif login_btn_count > 0:
            print("❌ 未登录")
            print("   在这个标签页中发现了登录按钮")
            print()
            print("   可能原因:")
            print("   1. 这不是你登录的那个标签页")
            print("   2. 登录状态已过期")
            print()
            print("   请在 Chrome 中重新登录，然后再运行这个脚本")
        else:
            print("⚠️  状态不确定，请查看浏览器窗口")
        
        print()
        print("6. 保持连接 10 秒...")
        for i in range(10, 0, -1):
            print(f"\r   {i} 秒...", end="", flush=True)
            time.sleep(1)
        
        print("\n\n7. 断开连接...")
        browser.close()
        
        print("\n✅ 完成！")
        print("   （Chrome 浏览器不会关闭，你可以继续使用）")
        
    except ConnectionRefusedError:
        print("❌ 无法连接到 Chrome")
        print()
        print("可能的原因:")
        print("  1. Chrome 没有以调试模式启动")
        print("  2. 调试端口不是 9222")
        print()
        print("请运行: ./start_chrome_debug.sh")
        
    except Exception as e:
        print(f"❌ 发生错误: {e}")
        import traceback
        traceback.print_exc()

print()
