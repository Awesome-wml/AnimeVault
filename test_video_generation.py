#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试豆包视频生成
直接调用一个分镜进行测试
"""
import sys
import os
import asyncio
from pathlib import Path

# 添加 backend 到路径
sys.path.insert(0, str(Path(__file__).parent / "backend"))

from core.doubao_automation import DoubaoVideoGenerator
from core.doubao_account_pool import DoubaoAccountPool


async def test_single_shot():
    """测试单个分镜生成"""
    
    print("=" * 60)
    print("豆包视频生成测试")
    print("=" * 60)
    
    # 1. 检查账号池状态
    print("\n1. 检查账号池状态...")
    pool = DoubaoAccountPool()
    status = pool.get_account_status()
    
    print(f"\n账号池状态：")
    for acc in status:
        print(f"  - {acc['name']}: 今日 {acc['today_used']}/{acc['daily_limit']}, "
              f"剩余 {acc['remaining']}, {'可用' if acc['available'] else '已满'}")
    
    print(f"\n总可用配额: {pool.get_total_available_quota()} 条")
    
    # 2. 获取可用账号
    account = pool.get_available_account()
    if not account:
        print("\n❌ 没有可用账号！")
        return
    
    print(f"\n2. 选择账号: {account['name']} (Profile: {account['profile_dir']})")
    
    # 3. 准备测试任务
    print("\n3. 准备测试任务...")
    
    # 测试任务（你可以修改这些参数）
    test_task = {
        "shot_no": 1,
        "prompt": "测试视频生成：一个阳光明媚的早晨，年轻人在练武场上挥洒汗水。",
        "text": "旁白：萧尘每天都在刻苦修炼。",
        "assets": []  # 暂时不上传资产，只测试提示词
    }
    
    print(f"  分镜号: {test_task['shot_no']}")
    print(f"  提示词: {test_task['prompt']}")
    print(f"  台词: {test_task['text']}")
    print(f"  资产数: {len(test_task['assets'])}")
    
    # 4. 确认执行
    print("\n" + "=" * 60)
    print("⚠️  即将打开浏览器并自动生成视频")
    print("=" * 60)
    confirm = input("\n确认执行测试？(y/n): ").strip().lower()
    
    if confirm != 'y':
        print("已取消测试")
        return
    
    # 5. 执行生成
    print("\n4. 开始生成视频...")
    print("-" * 60)
    
    try:
        project_root = Path(__file__).parent
        generator = DoubaoVideoGenerator(str(project_root))
        
        result = generator.generate_batch(
            profile_dir=account["profile_dir"],
            tasks=[test_task],
            interval=2
        )
        
        print("\n" + "=" * 60)
        print("生成完成！")
        print("=" * 60)
        print(f"✅ 成功: {len(result['success'])} 条")
        print(f"❌ 失败: {len(result['failed'])} 条")
        
        if result['success']:
            print(f"\n成功的分镜: {result['success']}")
            # 增加账号使用计数
            pool.increment_usage(account['id'])
            print(f"已更新账号 {account['name']} 的使用计数")
        
        if result['failed']:
            print(f"\n失败的分镜: {result['failed']}")
        
    except Exception as e:
        print(f"\n❌ 生成失败: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    # 运行测试
    asyncio.run(test_single_shot())
