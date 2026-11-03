"""视频生成API（豆包自动化）"""
from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from bson import ObjectId
from typing import List, Optional
import os
from pathlib import Path

from models.schema import ResponseModel
from db.mongo_client import get_db
from api.auth import get_current_user
from core.doubao_account_pool import DoubaoAccountPool
from core.doubao_automation import DoubaoVideoGenerator
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/video", tags=["视频生成"])

# 获取项目根目录
PROJECT_ROOT = Path(__file__).parent.parent.parent


@router.get("/accounts/status")
async def get_account_status(user: dict = Depends(get_current_user)):
    """获取豆包账号池状态"""
    try:
        pool = DoubaoAccountPool()
        status = pool.get_account_status()
        total_quota = pool.get_total_available_quota()
        
        return ResponseModel(
            data={
                "accounts": status,
                "total_available_quota": total_quota
            }
        )
    except Exception as e:
        logger.error(f"获取账号状态失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取账号状态失败: {str(e)}")


@router.post("/generate/batch")
async def generate_batch_videos(
    project_id: str,
    shot_ids: Optional[List[str]] = None,
    user: dict = Depends(get_current_user)
):
    """
    批量生成视频
    
    Args:
        project_id: 项目 ID
        shot_ids: 指定的分镜 ID 列表（可选，不传则处理所有分镜）
    """
    db = get_db()
    
    # 检查项目权限
    try:
        project = await db.projects.find_one({
            "_id": ObjectId(project_id),
            "user_id": str(user["_id"])
        })
    except Exception:
        raise HTTPException(status_code=400, detail="无效的项目ID")
    
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    
    # 获取分镜列表
    query = {
        "user_id": str(user["_id"]),
        "project_id": project_id
    }
    
    if shot_ids:
        # 指定分镜
        try:
            obj_ids = [ObjectId(sid) for sid in shot_ids]
            query["_id"] = {"$in": obj_ids}
        except:
            raise HTTPException(status_code=400, detail="无效的分镜ID")
    
    cursor = db.shots.find(query).sort("shot_no", 1)
    shots = await cursor.to_list(length=100)
    
    if not shots:
        raise HTTPException(status_code=404, detail="没有可用的分镜")
    
    # 检查账号池配额
    pool = DoubaoAccountPool()
    total_quota = pool.get_total_available_quota()
    
    if total_quota < len(shots):
        raise HTTPException(
            status_code=400,
            detail=f"配额不足：需要 {len(shots)} 条，今日剩余 {total_quota} 条"
        )
    
    # 分配任务到账号
    allocation = pool.allocate_tasks(len(shots))
    
    if not allocation:
        raise HTTPException(status_code=400, detail="没有可用的豆包账号")
    
    # 构建任务列表
    static_dir = PROJECT_ROOT / "static"
    
    results = []
    total_success = 0
    total_failed = 0
    
    for alloc in allocation:
        account_id = alloc["account_id"]
        account_name = alloc["account_name"]
        profile_dir = alloc["profile_dir"]
        task_indices = alloc["task_indices"]
        
        # 准备该账号的任务
        tasks = []
        for idx in task_indices:
            shot = shots[idx]
            
            # 收集资产文件路径
            assets = []
            
            # 添加图片
            if shot.get("img_path"):
                img_full_path = static_dir / shot["img_path"]
                if img_full_path.exists():
                    assets.append(str(img_full_path))
            
            # 添加音频
            if shot.get("audio_path"):
                audio_full_path = static_dir / shot["audio_path"]
                if audio_full_path.exists():
                    assets.append(str(audio_full_path))
            
            tasks.append({
                "shot_id": str(shot["_id"]),
                "shot_no": shot["shot_no"],
                "prompt": shot.get("prompt", ""),
                "text": shot.get("text", ""),
                "assets": assets
            })
        
        logger.info(f"账号 {account_name} 分配任务: {len(tasks)} 条")
        
        # 执行生成
        try:
            generator = DoubaoVideoGenerator(str(PROJECT_ROOT))
            result = generator.generate_batch(
                profile_dir=profile_dir,
                tasks=tasks,
                interval=3
            )
            
            total_success += len(result["success"])
            total_failed += len(result["failed"])
            
            results.append({
                "account_id": account_id,
                "account_name": account_name,
                "success_count": len(result["success"]),
                "failed_count": len(result["failed"]),
                "success_shots": result["success"],
                "failed_shots": result["failed"]
            })
            
        except Exception as e:
            logger.error(f"账号 {account_name} 生成失败: {e}")
            total_failed += len(tasks)
            results.append({
                "account_id": account_id,
                "account_name": account_name,
                "success_count": 0,
                "failed_count": len(tasks),
                "error": str(e)
            })
    
    return ResponseModel(
        message=f"批量生成完成：成功 {total_success} 条，失败 {total_failed} 条",
        data={
            "total_shots": len(shots),
            "success_count": total_success,
            "failed_count": total_failed,
            "results": results
        }
    )


@router.post("/generate/single")
async def generate_single_video(
    shot_id: str,
    account_id: Optional[str] = None,
    user: dict = Depends(get_current_user)
):
    """
    单条重新生成视频（失败重试）
    
    Args:
        shot_id: 分镜 ID
        account_id: 指定账号 ID（可选，不传则自动选择）
    """
    db = get_db()
    
    # 获取分镜
    try:
        shot = await db.shots.find_one({
            "_id": ObjectId(shot_id),
            "user_id": str(user["_id"])
        })
    except:
        raise HTTPException(status_code=400, detail="无效的分镜ID")
    
    if not shot:
        raise HTTPException(status_code=404, detail="分镜不存在")
    
    # 选择账号
    pool = DoubaoAccountPool()
    
    if account_id:
        account = pool.get_account_by_id(account_id)
        if not account:
            raise HTTPException(status_code=404, detail="账号不存在")
        
        # 检查配额
        usage = account.get("usage", {})
        if usage.get("count", 0) >= pool.DAILY_LIMIT:
            raise HTTPException(status_code=400, detail=f"账号 {account['name']} 今日配额已用完")
    else:
        account = pool.get_available_account()
        if not account:
            raise HTTPException(status_code=400, detail="没有可用的豆包账号")
    
    # 准备任务
    static_dir = PROJECT_ROOT / "static"
    assets = []
    
    if shot.get("img_path"):
        img_full_path = static_dir / shot["img_path"]
        if img_full_path.exists():
            assets.append(str(img_full_path))
    
    if shot.get("audio_path"):
        audio_full_path = static_dir / shot["audio_path"]
        if audio_full_path.exists():
            assets.append(str(audio_full_path))
    
    task = {
        "shot_id": str(shot["_id"]),
        "shot_no": shot["shot_no"],
        "prompt": shot.get("prompt", ""),
        "text": shot.get("text", ""),
        "assets": assets
    }
    
    # 执行生成
    try:
        generator = DoubaoVideoGenerator(str(PROJECT_ROOT))
        result = generator.generate_batch(
            profile_dir=account["profile_dir"],
            tasks=[task],
            interval=1
        )
        
        if result["success"]:
            # 增加账号使用计数
            pool.increment_usage(account["id"])
            
            return ResponseModel(
                message=f"分镜 {shot['shot_no']} 生成成功",
                data={
                    "shot_no": shot["shot_no"],
                    "account_name": account["name"]
                }
            )
        else:
            raise Exception("生成失败")
            
    except Exception as e:
        logger.error(f"单条生成失败: {e}")
        raise HTTPException(status_code=500, detail=f"生成失败: {str(e)}")
