#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
查找所有 Chrome Profile 中哪个登录了豆包
"""
import os
import subprocess
from pathlib import Path
from playwright.sync_api import sync_playwright
import time

# macOS Chrome 用户数据目录
CHROME_USER_DATA = Path.home() / "Library/Application Support/Google/Chrome"

def check_profile_doubao_login(profile_path, profile_name):
    """检查某个 Profile 是否登录了豆包"""
    print(f"\n{'=' * 60}")
    print(f"检查: {profile_name}")
    print(f"路径: {profile_path}")
    print(f"{'=' * 60}")
    
    try:
        with sync_playwright() as p:
            context = p.chromium.launch_persistent_context(
                str(profile_path),
                channel="chrome",
                headless=False,  # 显示浏览器，方便你看
                args=["--disable-blink-features=AutomationControlled"],
                viewport={"width": 1280, "height": 800},
            )
            
            page = context.pages[0] if context.pages else context.new_page()
            
            print("访问豆包...")
            page.goto("https://www.doubao.com/chat", timeout=30000)
            
            time.sleep(3)
            
            # 检查登录状态
            editor_count = page.locator("[contenteditable=true]").count()
            login_btn_count = page.get_by_text("登录", exact=True).count()
            
            # 尝试获取用户信息
            user_info = None
            try:
                # 查找头像或用户名元素
                user_avatar = page.locator("img[alt*='头像'], img[alt*='avatar'], [class*='avatar']").first
                if user_avatar.count() > 0:
                    user_info = "找到头像元素"
            except:
                pass
            
            print()
            if editor_count > 0:
                print("✅ 已登录豆包！")
                print(f"   - 找到 {editor_count} 个输入框")
                if user_info:
                    print(f"   - {user_info}")
                result = True
            elif login_btn_count > 0:
                print("❌ 未登录")
                print(f"   - 找到 {login_btn_count} 个登录按钮")
                result = False
            else:
                print("⚠️  状态不确定")
                result = None
            
            print("\n保持浏览器打开 5 秒，请查看...")
            for i in range(5, 0, -1):
                print(f"\r{i}...", end="", flush=True)
                time.sleep(1)
            
            print("\n关闭浏览器...")
            context.close()
            
            return result
            
    except Exception as e:
        print(f"❌ 错误: {e}")
        return False


def main():
    """主函数"""
    print()
    print("=" * 60)
    print("查找已登录豆包的 Chrome Profile")
    print("=" * 60)
    print()
    
    # 检查 Chrome 是否运行
    print("1. 检查 Chrome 进程...")
    result = subprocess.run(["pgrep", "-x", "Google Chrome"], capture_output=True)
    if result.returncode == 0:
        print("   ⚠️  Chrome 正在运行")
        print("   请关闭所有 Chrome 窗口，然后按回车继续...")
        input()
    else:
        print("   ✅ Chrome 未运行")
    
    print()
    print("2. 查找所有 Chrome Profile...")
    
    # 找到所有 Profile
    profiles = []
    
    # Default
    default_profile = CHROME_USER_DATA / "Default"
    if default_profile.exists():
        profiles.append(("Default", default_profile))
    
    # Profile 1, 2, 3...
    for item in sorted(CHROME_USER_DATA.iterdir()):
        if item.is_dir() and item.name.startswith("Profile "):
            profiles.append((item.name, item))
    
    if not profiles:
        print("❌ 未找到任何 Profile")
        return
    
    print(f"   找到 {len(profiles)} 个 Profile\n")
    
    logged_in_profiles = []
    
    # 逐个检查
    for i, (name, path) in enumerate(profiles, 1):
        print(f"\n进度: {i}/{len(profiles)}")
        
        is_logged_in = check_profile_doubao_login(path, name)
        
        if is_logged_in:
            logged_in_profiles.append((name, path))
        
        if i < len(profiles):
            print("\n准备检查下一个...")
            time.sleep(1)
    
    # 汇总结果
    print("\n\n")
    print("=" * 60)
    print("检查结果汇总")
    print("=" * 60)
    
    if logged_in_profiles:
        print(f"\n✅ 找到 {len(logged_in_profiles)} 个已登录豆包的 Profile:\n")
        for name, path in logged_in_profiles:
            print(f"  - {name}")
            print(f"    路径: {path}")
            print()
        
        print("请使用这些 Profile 路径配置 doubao_accounts.json")
    else:
        print("\n❌ 没有找到已登录豆包的 Profile")
        print("\n可能的原因:")
        print("  1. 你在浏览器中实际上没有登录豆包")
        print("  2. 豆包使用了不同的身份验证方式")
        print("  3. 需要在打开的浏览器窗口中手动登录")
    
    print("=" * 60)
    print()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n用户中断")
    except Exception as e:
        print(f"\n❌ 发生错误: {e}")
        import traceback
        traceback.print_exc()
