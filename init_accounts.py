#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
初始化豆包账号
用于首次登录多个账号，保存登录状态
"""
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright
import time

PROJECT_ROOT = Path(__file__).parent


def init_account(account_name):
    """初始化账号登录"""
    profile_dir = PROJECT_ROOT / ".doubao_profiles" / account_name
    profile_dir.mkdir(parents=True, exist_ok=True)
    
    print("=" * 60)
    print(f"初始化账号: {account_name}")
    print("=" * 60)
    print(f"Profile 目录: {profile_dir}")
    print()
    
    with sync_playwright() as p:
        print("1. 启动浏览器...")
        context = p.chromium.launch_persistent_context(
            str(profile_dir),
            channel="chrome",
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
            viewport={"width": 1280, "height": 800},
        )
        
        page = context.pages[0] if context.pages else context.new_page()
        
        print("2. 访问豆包...")
        page.goto("https://www.doubao.com/chat")
        
        time.sleep(3)
        
        # 检查状态
        editor_count = page.locator("[contenteditable=true]").count()
        
        if editor_count > 0:
            print("✅ 该账号已经登录")
        else:
            print("⚠️  该账号未登录，请在浏览器中完成登录")
            print()
            print("请执行以下步骤:")
            print("  1. 在打开的浏览器中点击【登录】")
            print("  2. 使用手机号 + 验证码登录")
            print("  3. 登录完成后，按回车继续")
            print()
            input("登录完成后按回车 >>> ")
            
            # 再次检查
            time.sleep(1)
            editor_count = page.locator("[contenteditable=true]").count()
            if editor_count > 0:
                print("✅ 登录成功！")
            else:
                print("❌ 仍未检测到登录，请检查")
        
        print()
        print("3. 保持浏览器打开 10 秒...")
        for i in range(10, 0, -1):
            print(f"\r倒计时: {i} 秒...  ", end="", flush=True)
            time.sleep(1)
        
        print("\n\n4. 关闭浏览器...")
        context.close()
        
        print(f"✅ 账号 {account_name} 初始化完成！")
        print(f"   登录状态已保存在: {profile_dir}")
        print()


def main():
    """主函数"""
    print()
    print("=" * 60)
    print("豆包账号初始化工具")
    print("=" * 60)
    print()
    print("用途: 为多个豆包账号初始化并保存登录状态")
    print("使用: python3 init_accounts.py [账号名]")
    print()
    
    # 获取账号列表
    if len(sys.argv) > 1:
        accounts = sys.argv[1:]
    else:
        print("请输入要初始化的账号名称（用空格分隔，例如: account_1 account_2）")
        accounts_input = input("账号名称: ").strip()
        accounts = accounts_input.split() if accounts_input else []
    
    if not accounts:
        print("❌ 未指定账号，退出")
        return
    
    print(f"将初始化 {len(accounts)} 个账号: {', '.join(accounts)}")
    print()
    
    for i, account in enumerate(accounts, 1):
        print(f"\n{'=' * 60}")
        print(f"进度: {i}/{len(accounts)}")
        print(f"{'=' * 60}\n")
        
        init_account(account)
        
        if i < len(accounts):
            print("\n准备初始化下一个账号...")
            time.sleep(2)
    
    print("\n" + "=" * 60)
    print("✅ 所有账号初始化完成！")
    print("=" * 60)
    print()
    print("现在你可以使用这些账号进行视频批量生成了。")
    print()


if __name__ == "__main__":
    main()
