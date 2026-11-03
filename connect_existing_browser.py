#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
连接到现有的 Chrome 浏览器（已登录状态）
"""
import os
from pathlib import Path
from playwright.sync_api import sync_playwright
import time

# macOS Chrome 用户数据目录
CHROME_USER_DATA = Path.home() / "Library/Application Support/Google/Chrome"

def list_chrome_profiles():
    """列出所有 Chrome Profile"""
    if not CHROME_USER_DATA.exists():
        print(f"❌ Chrome 用户数据目录不存在: {CHROME_USER_DATA}")
        return []
    
    profiles = []
    
    # Default profile
    default_profile = CHROME_USER_DATA / "Default"
    if default_profile.exists():
        profiles.append(("Default", str(default_profile)))
    
    # Profile 1, 2, 3...
    for item in CHROME_USER_DATA.iterdir():
        if item.is_dir() and item.name.startswith("Profile "):
            profiles.append((item.name, str(item)))
    
    return profiles


def connect_to_chrome_profile(profile_path):
    """连接到指定的 Chrome Profile"""
    print("=" * 60)
    print(f"连接到 Chrome Profile")
    print("=" * 60)
    print(f"Profile 路径: {profile_path}")
    print()
    
    # 检查 Chrome 是否正在运行
    import subprocess
    result = subprocess.run(["pgrep", "-x", "Google Chrome"], capture_output=True)
    if result.returncode == 0:
        print("⚠️  Chrome 正在运行，需要先关闭 Chrome")
        print("   请关闭所有 Chrome 窗口，然后按回车继续...")
        input()
    
    with sync_playwright() as p:
        print("1. 启动 Chrome（接管现有登录状态）...")
        
        try:
            context = p.chromium.launch_persistent_context(
                profile_path,
                channel="chrome",
                headless=False,
                args=[
                    "--disable-blink-features=AutomationControlled",
                ],
                viewport={"width": 1280, "height": 800},
            )
            
            page = context.pages[0] if context.pages else context.new_page()
            
            print("2. 访问豆包...")
            page.goto("https://www.doubao.com/chat", timeout=30000)
            
            time.sleep(3)
            
            # 检查登录状态
            print("3. 检查登录状态...")
            editor_count = page.locator("[contenteditable=true]").count()
            login_btn_count = page.get_by_text("登录", exact=True).count()
            
            print()
            print("-" * 60)
            
            if editor_count > 0:
                print("✅ 已登录！找到输入框")
                print()
                print("🎉 成功接管浏览器登录状态！")
            elif login_btn_count > 0:
                print("❌ 未登录，发现登录按钮")
                print()
                print("提示: 该 Profile 中可能没有登录豆包")
                print("      请尝试其他 Profile")
            else:
                print("⚠️  状态不确定")
            
            print("-" * 60)
            print()
            print("浏览器将保持打开 30 秒，你可以测试...")
            print("按 Ctrl+C 可以立即退出")
            print()
            
            try:
                for i in range(30, 0, -1):
                    print(f"\r倒计时: {i} 秒...  ", end="", flush=True)
                    time.sleep(1)
            except KeyboardInterrupt:
                print("\n\n用户中断")
            
            print("\n\n4. 关闭浏览器...")
            context.close()
            
            print("✅ 测试完成！")
            
        except Exception as e:
            print(f"❌ 连接失败: {e}")


def main():
    """主函数"""
    print()
    print("=" * 60)
    print("连接到现有 Chrome 浏览器")
    print("=" * 60)
    print()
    
    # 列出所有 Profile
    profiles = list_chrome_profiles()
    
    if not profiles:
        print("❌ 未找到 Chrome Profile")
        print(f"   检查路径: {CHROME_USER_DATA}")
        return
    
    print(f"找到 {len(profiles)} 个 Chrome Profile:\n")
    
    for i, (name, path) in enumerate(profiles, 1):
        print(f"{i}. {name}")
        print(f"   路径: {path}")
        print()
    
    # 选择 Profile
    try:
        choice = input(f"请选择要连接的 Profile (1-{len(profiles)}，直接回车选择第一个): ").strip()
        
        if not choice:
            index = 0
        else:
            index = int(choice) - 1
        
        if 0 <= index < len(profiles):
            profile_name, profile_path = profiles[index]
            print(f"\n✅ 选择: {profile_name}\n")
            
            connect_to_chrome_profile(profile_path)
        else:
            print("❌ 无效的选择")
    
    except KeyboardInterrupt:
        print("\n\n取消操作")
    except Exception as e:
        print(f"\n❌ 错误: {e}")


if __name__ == "__main__":
    main()
