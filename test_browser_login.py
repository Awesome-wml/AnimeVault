#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试浏览器登录状态
只打开豆包网页，检查是否保持登录状态
"""
import sys
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

# 项目根目录
PROJECT_ROOT = Path(__file__).parent

def test_login_status(profile_name="account_1"):
    """
    测试登录状态
    
    Args:
        profile_name: 账号名称，例如 account_1, account_2
    """
    profile_dir = PROJECT_ROOT / ".doubao_profiles" / profile_name
    profile_dir.mkdir(parents=True, exist_ok=True)
    
    print("=" * 60)
    print(f"测试豆包登录状态 - {profile_name}")
    print("=" * 60)
    print(f"Profile 目录: {profile_dir}")
    print()
    
    with sync_playwright() as p:
        print("1. 启动 Chrome 浏览器...")
        
        # 启动持久化上下文（接管已登录状态）
        context = p.chromium.launch_persistent_context(
            str(profile_dir),
            channel="chrome",
            headless=False,  # 显示浏览器窗口
            args=[
                "--disable-blink-features=AutomationControlled",
            ],
            viewport={"width": 1280, "height": 800},
        )
        
        page = context.pages[0] if context.pages else context.new_page()
        
        print("2. 访问豆包网站...")
        page.goto("https://www.doubao.com/chat", timeout=30000)
        
        # 等待页面加载
        time.sleep(3)
        
        # 检查登录状态
        print("3. 检查登录状态...")
        
        # 方法1: 检查是否有输入框（已登录）
        editor_count = page.locator("[contenteditable=true]").count()
        
        # 方法2: 检查是否有登录按钮（未登录）
        login_btn_count = page.get_by_text("登录", exact=True).count()
        
        print()
        print("-" * 60)
        
        if editor_count > 0:
            print("✅ 状态: 已登录")
            print(f"   找到 {editor_count} 个输入框")
            print()
            print("🎉 成功！浏览器已保持登录状态")
        elif login_btn_count > 0:
            print("❌ 状态: 未登录")
            print(f"   找到 {login_btn_count} 个登录按钮")
            print()
            print("⚠️  请在浏览器中手动登录豆包")
            print("   登录后，登录状态会自动保存到 Profile 目录")
            print("   下次运行时将自动保持登录")
        else:
            print("⚠️  状态: 不确定，请检查页面")
        
        print("-" * 60)
        print()
        print("提示:")
        print("  - 浏览器将保持打开状态30秒，你可以查看页面")
        print("  - 如果未登录，请现在手动登录")
        print("  - 按 Ctrl+C 可以立即退出")
        print()
        
        # 保持浏览器打开30秒
        try:
            for i in range(30, 0, -1):
                print(f"\r倒计时: {i} 秒...  ", end="", flush=True)
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n\n用户中断")
        
        print("\n\n4. 关闭浏览器...")
        context.close()
        
        print("✅ 测试完成！")
        print()
        print(f"登录状态已保存在: {profile_dir}")


if __name__ == "__main__":
    # 可以指定账号名称
    account = sys.argv[1] if len(sys.argv) > 1 else "account_1"
    
    print()
    print(f"测试账号: {account}")
    print()
    
    test_login_status(account)
