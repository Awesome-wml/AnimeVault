"""视频生成API（豆包自动化）"""
from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks, UploadFile, File
from starlette.concurrency import run_in_threadpool
from bson import ObjectId
from typing import List, Optional
import os
import json
from pathlib import Path

from models.schema import ResponseModel
from db.mongo_client import get_db
from api.auth import get_current_user
from core.doubao_account_pool import DoubaoAccountPool
from core.doubao_automation import DoubaoVideoGenerator, to_unwatermarked_url, _detect_codec_fourcc, _HEVC_MARKS
from core.doubao_chrome import (DOUBAO_CHAT_URL, LoginCheckError, check_account_login,
                                ensure_debug_port, inject_cookies_into_chrome, launch_chrome,
                                probe_debug_port, profile_lock_pid)
from core.providers import fake
from core.video_models import get_video_model
from core.video_prompt import build_upload_plan
from core.style_library import build_video_style_line, medium_key, style_mismatch_warnings, style_ref
from core.script_text import scene_location_of
from utils.file_util import FileUtil
import json
import logging

logger = logging.getLogger(__name__)


router = APIRouter(prefix="/api/video", tags=["视频生成"])

# 获取项目根目录
PROJECT_ROOT = Path(__file__).parent.parent.parent

# SSE事件队列：project_id -> 队列
import asyncio
sse_queues: dict[str, asyncio.Queue] = {}

def video_task_params(shot: dict, project: Optional[dict]) -> dict:
    """一次视频生成的模型与时长：模型取项目设置（没有则用拆段时的模型），
    时长取分镜段的 duration（钳到模型范围）；旧格式分镜（没有 lines）照旧按模型最长时长生成。"""
    model = get_video_model((project or {}).get("video_model") or shot.get("model_key"))
    duration = model["max_duration"]
    if shot.get("lines"):
        try:
            duration = int(round(float(shot.get("duration") or duration)))
        except (TypeError, ValueError):
            pass
        duration = min(max(duration, model["min_duration"]), model["max_duration"])
    return {"duration": duration, "model_name": model["name"], "model_key": model["key"],
            "reference_types": model["reference_types"], "max_files": model["max_files"]}


async def build_video_task(db, shot: dict, project: Optional[dict], chars: list, scenes: list, props: list,
                           static_dir) -> dict:
    """一次视频生成的任务：参考图（按上传顺序）+ 提示词 + 模型与时长。

    用哪些资产、什么顺序由 core.asset_binding.collect_bindings 决定（剧本场次地点参与场景归属）；
    参考图上传顺序与提示词里的【@图片N】由 core.video_prompt.build_upload_plan 用同一个列表产出。
    视频段（有 lines）按五段结构组装提示词；旧格式分镜照旧发 video_prompt 原文。
    """
    params = video_task_params(shot, project)
    model = get_video_model(params["model_key"])
    extra_refs = []
    # 上一段关键帧：用户开启才截
    if shot.get("use_prev_frame"):
        shot_no = shot["shot_no"]
        prev_shot = await db.shots.find_one({"project_id": shot["project_id"], "shot_no": shot_no - 1})
        if prev_shot and prev_shot.get("video_path"):
            import subprocess
            prev_vid = static_dir / prev_shot["video_path"]
            if prev_vid.exists():
                frame_name = f"prev_frame_shot{shot_no}.png"
                frame_path = static_dir / "images" / frame_name
                frame_path.parent.mkdir(exist_ok=True)
                subprocess.run(["ffmpeg", "-y", "-sseof", "-0.5", "-i", str(prev_vid), "-frames:v", "1", str(frame_path)],
                               capture_output=True, timeout=15)
                if frame_path.exists():
                    extra_refs.append({"type": "关键帧", "name": "上一段尾帧", "path": str(frame_path)})
                    logger.info(f"分镜{shot_no} 已添加上一段关键帧: {frame_name}")
    plan = build_upload_plan(shot, chars, scenes, props, static_dir, model,
                             scene_location=await scene_location_of(db, shot), extra_refs=extra_refs,
                             genre=str((project or {}).get("genre") or ""),
                             style_suffix=build_video_style_line(**style_ref(project)))
    style_warnings = style_mismatch_warnings(plan["refs"], list(chars) + list(scenes) + list(props),
                                             medium_key(**style_ref(project)))
    for w in plan["warnings"] + style_warnings:
        logger.warning(f"分镜 {shot['shot_no']}：{w}")
    return {
        "shot_id": str(shot["_id"]),
        "shot_no": shot["shot_no"],
        "prompt": plan["prompt"],
        "text": shot.get("text", ""),
        "assets": plan["files"],
        "references": [r["name"] for r in plan["refs"]],
        "style_warnings": style_warnings,
        **params,
    }


async def push_sse(project_id: str, event: dict):
    """向指定项目的SSE队列推送事件"""
    q = sse_queues.get(project_id)
    if q:
        await q.put(event)
        logger.info("[SSE] 已入队 project=%s shot=%s step=%s progress=%s msg=%s 队列待消费=%d",
                    project_id, event.get("shot_no"), event.get("step"),
                    event.get("progress"), event.get("msg"), q.qsize())
    else:
        logger.warning("[SSE] 无前端连接队列，事件被丢弃 project=%s event=%s", project_id, event)

@router.get("/events/{project_id}")
async def sse_events(project_id: str):
    """SSE推送：视频生成完成等事件"""
    from sse_starlette.sse import EventSourceResponse
    q = sse_queues.get(project_id)
    if q is None:
        q = asyncio.Queue()
        sse_queues[project_id] = q
    logger.info("[SSE] 前端连接建立 project=%s 当前在线项目=%d", project_id, len(sse_queues))

    async def event_generator():
        try:
            while True:
                msg = await q.get()
                # 前端按 JSON 解析（shot_no/step/progress/msg），不能用 str(dict) 的 Python 写法
                logger.info("[SSE] 下发帧 project=%s event=%s", project_id, msg)
                yield {"event": "message", "data": json.dumps(msg, ensure_ascii=False)}
        finally:
            logger.info("[SSE] 前端断开 project=%s", project_id)
            # 仅当当前队列仍是自己时才移除，避免旧连接断开误删新连接的队列
            if sse_queues.get(project_id) is q:
                sse_queues.pop(project_id, None)

    return EventSourceResponse(event_generator())



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
                "total_available_quota": total_quota,
                "daily_limit": pool.DAILY_LIMIT,
                "batch_unknown_cap": pool.BATCH_UNKNOWN_CAP,
                "parallel_max": pool.parallel_max(),
            }
        )
    except Exception as e:
        logger.error(f"获取账号状态失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取账号状态失败: {str(e)}")


@router.get("/accounts")
async def list_accounts(user: dict = Depends(get_current_user)):
    """列出所有豆包账号"""
    try:
        pool = DoubaoAccountPool()
        raw = pool.accounts
        # 不把 cookie 原文返回前端；附带额度摘要、remaining_estimate、limit_mode
        accounts = [pool.public_view(acc, raw) for acc in raw]
        return ResponseModel(
            data={
                "accounts": accounts,
                "daily_limit": pool.DAILY_LIMIT
            }
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取账号列表失败: {str(e)}")


@router.post("/accounts")
async def add_account(data: dict, user: dict = Depends(get_current_user)):
    """添加豆包账号 - 自动创建 profile 并打开 Chrome 登录"""
    name = data.get("name", "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="账号名称不能为空")
    
    pool = DoubaoAccountPool()
    
    # 检查重名
    for acc in pool.accounts:
        if acc["name"] == name:
            raise HTTPException(status_code=400, detail=f"账号名 '{name}' 已存在")
    
    # 自动生成 profile 目录
    existing_ids = [a["id"] for a in pool.accounts]
    idx = 1
    while f"account_{idx}" in existing_ids:
        idx += 1
    profile_dir = f".doubao_profiles/account_{idx}"
    
    new_account = {
        "id": f"account_{idx}",
        "name": name,
        "profile_dir": profile_dir,
        "cookies": [],
        "enabled": True,
        "logged_in": False,
        "usage": {"date": str(__import__('datetime').date.today()), "count": 0}
    }
    
    pool.add_account(new_account)
    new_account["debug_port"] = ensure_debug_port(pool, new_account)

    # 自动打开 Chrome 让用户登录（系统 Chrome 独立窗口，带调试端口，之后「检查登录」直接连上读取）
    launch_chrome(str(PROJECT_ROOT / profile_dir), new_account["debug_port"])
    return ResponseModel(
        message=f"账号 '{name}' 已创建，Chrome 已打开，请在浏览器中登录豆包，登录成功后点「登录」检查",
        data={"account": {k: v for k, v in new_account.items() if k != "cookies"}}
    )


@router.post("/accounts/{account_id}/check-login")
async def check_login(account_id: str, user: dict = Depends(get_current_user)):
    """检查登录状态（见 core.doubao_chrome.check_account_login）：
    优先连该账号已打开的 Chrome（调试端口）读 cookie；其次用数据库 cookie；资料目录被占用时立即报错；
    整个检查最多 45 秒，超时报错。"""
    pool = DoubaoAccountPool()
    account = pool.get_account_by_id(account_id)
    if not account:
        raise HTTPException(status_code=404, detail="账号不存在")
    try:
        result = await check_account_login(pool, account, PROJECT_ROOT)
    except LoginCheckError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))
    except Exception as e:
        logger.exception("检查登录失败")
        raise HTTPException(status_code=500, detail=f"检查失败: {e}")
    return ResponseModel(message=result["message"],
                         data={"logged_in": result["logged_in"], "via": result["via"], "quota": result.get("quota")})


@router.put("/accounts/{account_id}")
async def update_account(account_id: str, data: dict, user: dict = Depends(get_current_user)):
    """更新账号（名称、启用状态）"""
    pool = DoubaoAccountPool()
    account = pool.get_account_by_id(account_id)
    
    if not account:
        raise HTTPException(status_code=404, detail="账号不存在")
    
    patch = {}
    if "name" in data and data["name"].strip():
        patch["name"] = data["name"].strip()
    if "enabled" in data:
        patch["enabled"] = bool(data["enabled"])
    if "profile_dir" in data and data["profile_dir"].strip():
        patch["profile_dir"] = data["profile_dir"].strip()

    pool.update_account(account_id, patch)
    return ResponseModel(message="账号更新成功")


@router.delete("/accounts/{account_id}")
async def delete_account(account_id: str, user: dict = Depends(get_current_user)):
    """删除账号，并清理对应临时 Profile 目录"""
    import shutil
    pool = DoubaoAccountPool()
    account = pool.get_account_by_id(account_id)

    if not account:
        raise HTTPException(status_code=404, detail="账号不存在")

    pool.delete_account(account_id)

    # 清理临时扫码目录（cookie 已不依赖目录）；只删项目内 .doubao_profiles 相对目录，
    # 绝不动系统 Chrome 的绝对路径目录。
    profile_dir = account.get("profile_dir")
    if profile_dir and not profile_dir.startswith("/") and profile_dir.startswith(".doubao_profiles"):
        profile_path = PROJECT_ROOT / profile_dir
        try:
            if profile_path.exists():
                shutil.rmtree(profile_path, ignore_errors=True)
        except Exception as e:
            logger.warning(f"清理 Profile 目录失败: {e}")

    return ResponseModel(message=f"账号 '{account['name']}' 已删除")


@router.put("/accounts/{account_id}/rename")
async def rename_account(account_id: str, body: dict, user: dict = Depends(get_current_user)):
    """重命名账号"""
    pool = DoubaoAccountPool()
    account = pool.get_account_by_id(account_id)
    
    if not account:
        raise HTTPException(status_code=404, detail="账号不存在")
    
    new_name = body.get("name", "").strip()
    if not new_name:
        raise HTTPException(status_code=400, detail="名称不能为空")
    
    pool.rename_account(account_id, new_name)
    
    return ResponseModel(message=f"已重命名为 '{new_name}'")


@router.post("/generate/batch")
async def generate_batch_videos(
    project_id: str,
    shot_ids: Optional[List[str]] = None,
    parallel: bool = False,
    limit: int = 0,
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

    # 安全过滤：跳过已经有视频的分镜
    shots = [s for s in shots if not s.get("video_path")]

    # 限制执行条数
    if limit > 0:
        shots = shots[:limit]

    if not shots:
        raise HTTPException(status_code=404, detail="所有分镜都已生成视频")

    # 构建任务列表（共用）
    static_dir = FileUtil.get_static_dir()
    # 统一 SSE 状态回调：自动化线程 → 主事件循环 → 项目 SSE 队列（并行、串行、单条共用）
    loop = asyncio.get_event_loop()

    def sse_status_callback(data: dict):
        logger.info("[SSE] 自动化回调进入 project=%s data=%s", project_id, data)
        try:
            fut = asyncio.run_coroutine_threadsafe(push_sse(project_id, data), loop)

            def _log_exc(f):
                try:
                    f.result()
                except Exception as e:
                    logger.warning("SSE 推送协程异常: %s", e)
            fut.add_done_callback(_log_exc)
        except Exception as e:
            logger.warning("SSE 状态推送失败: %s", e)

    all_chars = await db.characters.find({"project_id": project_id}).to_list(None)
    all_scenes = await db.scenes.find({"project_id": project_id}).to_list(None)
    all_props = await db.props.find({"project_id": project_id}).to_list(None)

    tasks = []
    for shot in shots:
        tasks.append(await build_video_task(db, shot, project, all_chars, all_scenes, all_props, static_dir))

    # ===== 并行模式：一个账号开多 page =====
    if parallel:
        pool = DoubaoAccountPool()
        acc = pool.get_available_account()
        if not acc:
            raise HTTPException(status_code=400, detail="没有可用的豆包账号")
        # 本批最多条数：标签页上限 5，且不超过该账号剩余可生成条数（会员未知成本时按 BATCH_UNKNOWN_CAP）
        acc_cap = pool.remaining_info(acc, pool.accounts)["batch_cap"]
        max_parallel = max(1, min(pool.PARALLEL_TABS, len(tasks), acc_cap))
        logger.info(f"并行模式：账号 {acc['name']}，{len(tasks)} 条任务，本批 {max_parallel} 条")

        generator = DoubaoVideoGenerator(str(PROJECT_ROOT), status_callback=sse_status_callback)

        # 每个视频下好就立刻写库
        async def on_ready(shot_id, shot_no, video_path):
            await db.shots.update_one(
                {"_id": ObjectId(shot_id)},
                {"$set": {"video_path": video_path, "status": "done"}}
            )
            # 并行模式此前不计用量，账号今日配额永远显示没用过
            pool.increment_usage(acc["id"])
            logger.info(f"分镜 {shot_no} video_path 已写入: {video_path}")

        def on_ready_sync(shot_id, shot_no, video_path, frame=""):
            # 在工作线程里等写库完成，保证接口返回时 video_path 已落库
            asyncio.run_coroutine_threadsafe(on_ready(shot_id, shot_no, video_path), loop).result(timeout=30)

        result = await run_in_threadpool(
            generator.generate_parallel,
            profile_dir=acc.get("profile_dir", ""),
            cookies=acc.get("cookies", []),
            tasks=tasks,
            max_parallel=max_parallel,
            on_video_ready=on_ready_sync,
        )
        # 回写最新 cookie（续期）与额度读数 / 单条成本
        if generator.last_cookies:
            pool.set_cookies(acc["id"], generator.last_cookies)
        pool.save_generation_quota(acc["id"], generator)
        return ResponseModel(data={
            "total_shots": result["total"],
            "success_count": len(result["success"]),
            "failed_count": len(result["failed"]),
            "results": [{
                "account_name": acc["name"],
                "success_count": len(result["success"]),
                "failed_count": len(result["failed"]),
            }],
            "videos": result["videos"],
        })

    # ===== 原有串行多账号模式 =====
    # 检查账号池配额
    pool = DoubaoAccountPool()
    total_quota = pool.get_total_available_quota()

    if total_quota < len(shots):
        raise HTTPException(
            status_code=400,
            detail=f"额度不足：需要 {len(shots)} 条，各账号本批最多可生成 {total_quota} 条"
        )

    allocation = pool.allocate_tasks(len(shots))

    if not allocation:
        raise HTTPException(status_code=400, detail="没有可用的豆包账号")
    results = []
    total_success = 0
    total_failed = 0
    
    for alloc in allocation:
        account_id = alloc["account_id"]
        account_name = alloc["account_name"]
        profile_dir = alloc.get("profile_dir", "")
        alloc_cookies = alloc.get("cookies", [])
        task_indices = alloc["task_indices"]
        
        # 准备该账号的任务
        all_chars = await db.characters.find({"project_id": project_id}).to_list(None)
        all_scenes = await db.scenes.find({"project_id": project_id}).to_list(None)
        all_props = await db.props.find({"project_id": project_id}).to_list(None)
        tasks = [await build_video_task(db, shots[idx], project, all_chars, all_scenes, all_props, static_dir)
                 for idx in task_indices]
        
        logger.info(f"账号 {account_name} 分配任务: {len(tasks)} 条")
        
        # 执行生成
        try:
            generator = DoubaoVideoGenerator(str(PROJECT_ROOT), status_callback=sse_status_callback)
            result = await run_in_threadpool(
                generator.generate_batch,
                profile_dir=profile_dir,
                cookies=alloc_cookies,
                tasks=tasks,
                interval=3
            )
            
            total_success += len(result["success"])
            total_failed += len(result["failed"])

            # 把视频路径写回 MongoDB
            for task in tasks:
                sn = task["shot_no"]
                vp = result.get("videos", {}).get(sn, "")
                if vp:
                    await db.shots.update_one(
                        {"_id": ObjectId(task["shot_id"])},
                        {"$set": {"video_path": vp, "status": "done"}}
                    )
                    logger.info(f"分镜 {sn} video_path 已写入: {vp}")

            results.append({
                "account_id": account_id,
                "account_name": account_name,
                "success_count": len(result["success"]),
                "failed_count": len(result["failed"]),
                "success_shots": result["success"],
                "failed_shots": result["failed"],
                "failed_reasons": {str(k): v.get("msg", "") for k, v in result.get("reasons", {}).items()},
            })

            # 回写最新 cookie（续期）与额度读数 / 单条成本
            if generator.last_cookies:
                pool.set_cookies(account_id, generator.last_cookies)
            pool.save_generation_quota(account_id, generator)

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
    project = await db.projects.find_one({"_id": ObjectId(shot["project_id"])}) if ObjectId.is_valid(shot.get("project_id") or "") else None
    
    # 选择账号
    pool = DoubaoAccountPool()
    
    if account_id:
        account = pool.get_account_by_id(account_id)
        if not account:
            raise HTTPException(status_code=404, detail="账号不存在")
        
        # 检查额度（会员按额度，非会员按每日限额）
        info = pool.remaining_info(account, pool.accounts)
        if not info["available"]:
            msg = "会员额度已用完" if info["limit_mode"] == "member" else "今日配额已用完"
            raise HTTPException(status_code=400, detail=f"账号 {account['name']} {msg}")
    else:
        account = pool.get_available_account()
        if not account:
            raise HTTPException(status_code=400, detail="没有可用的豆包账号")
    
    # 准备任务
    static_dir = FileUtil.get_static_dir()
    pid = shot["project_id"]
    task = await build_video_task(
        db, shot, project,
        await db.characters.find({"project_id": pid}).to_list(None),
        await db.scenes.find({"project_id": pid}).to_list(None),
        await db.props.find({"project_id": pid}).to_list(None),
        static_dir)
    logger.info(f"  共 {len(task['assets'])} 个素材文件")

    # 单条生成同样接 SSE 进度回调：自动化线程 → 主事件循环 → 项目 SSE 队列
    loop = asyncio.get_event_loop()

    def sse_status_callback(data: dict):
        logger.info("[SSE] 单条自动化回调进入 project=%s data=%s", pid, data)
        try:
            fut = asyncio.run_coroutine_threadsafe(push_sse(pid, data), loop)

            def _log_exc(f):
                try:
                    f.result()
                except Exception as e:
                    logger.warning("SSE 推送协程异常: %s", e)
            fut.add_done_callback(_log_exc)
        except Exception as e:
            logger.warning("SSE 状态推送失败: %s", e)

    # 执行生成
    try:
        logger.info(f"开始生成: shot_id={shot_id}, account={account['name']}, cookies={len(account.get('cookies', []))} 个")
        generator = DoubaoVideoGenerator(str(PROJECT_ROOT), status_callback=sse_status_callback)
        logger.info("正在启动 Chrome...")
        result = await run_in_threadpool(
            generator.generate_batch,
            profile_dir=account.get("profile_dir", ""),
            cookies=account.get("cookies", []),
            tasks=[task],
            interval=1
        )
        logger.info(f"生成完成: {result}")
        pool.save_generation_quota(account["id"], generator)

        if result["success"]:
            # 增加账号使用计数
            pool.increment_usage(account["id"])
            # 回写最新 cookie（续期）
            if generator.last_cookies:
                pool.set_cookies(account["id"], generator.last_cookies)

            # 保存视频路径到数据库
            video_path = result.get("videos", {}).get(shot["shot_no"], "")
            if video_path:
                await db.shots.update_one(
                    {"_id": ObjectId(shot_id)},
                    {"$set": {"video_path": video_path}}
                )

            return ResponseModel(
                message=f"分镜 {shot['shot_no']} 生成成功",
                data={
                    "shot_no": shot["shot_no"],
                    "account_name": account["name"],
                    "video_path": video_path
                }
            )
        else:
            # 细分失败原因（被拒绝/额度/超时/已生成但没抓到直链+对话URL），不要笼统写「生成失败」
            fail = result.get("reasons", {}).get(shot["shot_no"]) or {}
            raise Exception(fail.get("msg") or "生成失败")
            
    except Exception as e:
        logger.error(f"单条生成失败: {e}")
        raise HTTPException(status_code=500, detail=f"生成失败: {str(e)}")


# ===== 手动补录视频（自动化抓取失败时，人工上传文件 / 粘贴直链）=====
VIDEO_EXTS = {".mp4", ".mov", ".webm", ".m4v", ".mkv"}


def _save_video_bytes(shot_no: int, data: bytes, ext: str) -> str:
    """把视频字节存到 static/videos，返回相对路径 videos/xxx.ext。"""
    import time as _time
    videos_dir = FileUtil.get_static_dir() / "videos"
    videos_dir.mkdir(parents=True, exist_ok=True)
    ext = ext if ext in VIDEO_EXTS else ".mp4"
    filename = f"shot_{int(shot_no):03d}_{int(_time.time())}{ext}"
    save_path = videos_dir / filename
    with open(save_path, "wb") as f:
        f.write(data)
    logger.info("手动补录视频已保存: %s (%.2f MB)", save_path, len(data) / 1048576)
    return f"videos/{filename}"


async def _get_shot_or_404(db, shot_id: str, user: dict):
    try:
        shot = await db.shots.find_one({
            "_id": ObjectId(shot_id),
            "user_id": str(user["_id"])
        })
    except Exception:
        raise HTTPException(status_code=400, detail="无效的分镜ID")
    if not shot:
        raise HTTPException(status_code=404, detail="分镜不存在")
    return shot


@router.post("/shots/{shot_id}/upload-video")
async def upload_shot_video(
    shot_id: str,
    file: UploadFile = File(...),
    user: dict = Depends(get_current_user),
):
    """人工上传本地视频文件（选取 / 拖拽均可），绑定到该分镜。"""
    db = get_db()
    shot = await _get_shot_or_404(db, shot_id, user)

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="上传文件为空")

    # 扩展名：优先用文件名后缀，其次按 content-type 兜底
    name = (file.filename or "").lower()
    ext = next((e for e in VIDEO_EXTS if name.endswith(e)), "")
    if not ext:
        ct = (file.content_type or "").lower()
        ext_map = {"video/mp4": ".mp4", "video/quicktime": ".mov",
                   "video/webm": ".webm", "video/x-matroska": ".mkv"}
        ext = ext_map.get(ct, ".mp4")

    video_path = _save_video_bytes(shot.get("shot_no", 0), data, ext)
    await db.shots.update_one(
        {"_id": ObjectId(shot_id)},
        {"$set": {"video_path": video_path, "status": "done"}}
    )
    logger.info(f"分镜 {shot.get('shot_no')} 手动上传视频: {video_path}")
    return ResponseModel(message="视频已上传", data={"video_path": video_path})


@router.post("/shots/{shot_id}/url-video")
async def fetch_shot_video_by_url(
    shot_id: str,
    body: dict,
    user: dict = Depends(get_current_user),
):
    """粘贴豆包视频直链，后端下载后绑定到该分镜。"""
    import httpx
    db = get_db()
    shot = await _get_shot_or_404(db, shot_id, user)

    video_url = (body.get("url") or "").strip()
    if not video_url:
        raise HTTPException(status_code=400, detail="视频地址不能为空")
    # 豆包直链一律改成无水印（lr=unwatermarked）再下载
    video_url = to_unwatermarked_url(video_url)

    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=60.0) as client:
            resp = await client.get(video_url, headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                              "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
            })
            resp.raise_for_status()
            data = resp.content
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"下载视频失败: {e}")

    if not data:
        raise HTTPException(status_code=400, detail="下载内容为空")

    # 视频头校验（mp4 ftyp 或 webm EBML）
    is_mp4 = b"ftyp" in data[:65536]
    is_webm = data[:4] == b"\x1a\x45\xdf\xa3"
    if not (is_mp4 or is_webm):
        raise HTTPException(status_code=400, detail="链接内容不像视频文件，请检查直链是否正确")

    ct = (resp.headers.get("content-type") or "").lower()
    ext = ".webm" if "webm" in ct else ".mp4"
    if video_url.lower().rsplit(".", 1)[-1][:3] in ("mov",):
        ext = ".mov"

    video_path = _save_video_bytes(shot.get("shot_no", 0), data, ext)
    await db.shots.update_one(
        {"_id": ObjectId(shot_id)},
        {"$set": {"video_path": video_path, "status": "done"}}
    )
    logger.info(f"分镜 {shot.get('shot_no')} 按直链下载视频: {video_path}")
    return ResponseModel(message="视频已下载并绑定", data={"video_path": video_path})


@router.post("/accounts/{account_id}/launch")
async def launch_doubao_page(account_id: str, body: dict = None,
                             user: dict = Depends(get_current_user)):
    """打开豆包页面（人工排查 / 手动下载视频用）。先注入数据库 cookie，保证打开即已登录。"""
    pool = DoubaoAccountPool()
    account = pool.get_account_by_id(account_id)
    if not account:
        raise HTTPException(status_code=404, detail="账号不存在")

    if not account.get("profile_dir"):
        raise HTTPException(status_code=400, detail="该账号没有资料目录")
    target_url = (body or {}).get("url") or DOUBAO_CHAT_URL
    port = ensure_debug_port(pool, account)
    profile_path = str(PROJECT_ROOT / account["profile_dir"])
    # 资料目录已被一个没带调试端口的 Chrome 占用时，新参数不会生效，提示用户关掉旧窗口
    stale = profile_lock_pid(profile_path) and not probe_debug_port(port)
    launch_chrome(profile_path, port, target_url)
    # 把数据库里的 cookie 注入该常驻 Chrome（profile 本地缺会话时也能打开即登录），并写回资料目录
    if account.get("cookies"):
        injected = inject_cookies_into_chrome(port, account["cookies"], target_url)
        if not injected:
            logger.warning("账号 %s 打开后 cookie 注入未成功，可能仍是未登录页", account["name"])
    msg = f"已在 Chrome 打开豆包页面（账号 {account['name']}）"
    if stale:
        msg += "。该账号的旧 Chrome 窗口不支持直接检查登录，请关闭它后再点「打开」"
    return ResponseModel(message=msg)


# ===== 导出剪映 =====
import zipfile, io, os
from fastapi.responses import StreamingResponse

@router.get("/export/jianying")
async def export_jianying(project_id: str, video_set_id: str = "", user: dict = Depends(get_current_user)):
    """一键导出到剪映：自动写草稿并打开剪映"""
    import json, uuid, subprocess, time
    from pathlib import Path as P

    db = get_db()
    from bson import ObjectId
    try:
        project = await db.projects.find_one({"_id": ObjectId(project_id), "user_id": str(user["_id"])})
    except Exception:
        raise HTTPException(status_code=400, detail="无效的项目ID")
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    project_name = (project.get("name") or project.get("title") or "未命名")[:20]
    query = {"project_id": project_id, "user_id": str(user["_id"]), "video_path": {"$ne": None}}
    if video_set_id:
        query["video_set_id"] = video_set_id
    shots = await db.shots.find(query).sort("shot_no", 1).to_list(None)

    static_dir = FileUtil.get_static_dir()
    clips = []
    skipped_hevc = []
    for s in shots:
        vp = s.get("video_path")
        if not vp:
            continue
        fpath = static_dir / vp
        if not fpath.exists():
            continue
        try:
            codec = _detect_codec_fourcc(fpath.read_bytes())
        except Exception:
            codec = None
        if codec and codec.encode() in _HEVC_MARKS:
            logger.warning("导出剪映草稿跳过 H.265/HEVC 素材 shot=%s %s", s["shot_no"], vp)
            skipped_hevc.append(s["shot_no"])
            continue
        clips.append((s["shot_no"], str(fpath.resolve())))

    if not clips:
        return {"ok": False, "msg": "没有可导入剪映的视频（现有素材为 H.265，需先转码或重跑成 H.264）"}

    # 找剪映草稿目录：优先用配置，否则自动检测mac/windows默认路径
    import platform
    from config.settings import settings
    if settings.JIANYING_DRAFT_DIR:
        draft_root = P(settings.JIANYING_DRAFT_DIR).expanduser()
    else:
        system = platform.system()
        if system == "Darwin":
            draft_root = P.home() / "Movies/JianyingPro/User Data/Projects/com.lveditor.draft"
        elif system == "Windows":
            draft_root = P.home() / "AppData/Local/JianyingPro/User Data/Projects/com.lveditor.draft"
        else:
            draft_root = P.home() / "Movies/JianyingPro/User Data/Projects/com.lveditor.draft"
    if not draft_root.exists():
        return {"ok": False, "msg": f"找不到剪映草稿目录: {draft_root}"}

    # 从备份模板复制（永久模板，不依赖用户手动建的草稿）
    template_dir = (P(settings.JIANYING_TEMPLATE_DIR).expanduser() if settings.JIANYING_TEMPLATE_DIR
                    else P(__file__).parent.parent / ".jianying_template")
    if not (template_dir / "draft_info.json").exists():
        return {"ok": False, "msg": "找不到模板草稿，请先手动建一个含视频的草稿"}

    # 新草稿名：小说名+时间戳
    ts = int(time.time())
    draft_name = f"{project_name}_{ts}"
    new_draft = draft_root / draft_name
    if new_draft.exists():
        import shutil
        shutil.rmtree(new_draft)
    import shutil
    shutil.copytree(template_dir, new_draft)

    # 读取模板
    info_path = new_draft / "draft_info.json"
    meta_path = new_draft / "draft_meta_info.json"
    d = json.load(open(info_path))
    meta = json.load(open(meta_path))

    tmpl_video = d["materials"]["videos"][0]
    tmpl_seg = d["tracks"][0]["segments"][0]
    tmpl_track = d["tracks"][0]
    tmpl_canvas = d["materials"]["canvases"][0] if d["materials"].get("canvases") else None
    DUR = tmpl_seg["target_timerange"]["duration"]

    new_videos, new_speeds, new_canvases, new_segments = [], [], [], []
    cur = 0
    for shot_no, path in clips:
        vid = str(uuid.uuid4()).upper()
        sid = str(uuid.uuid4()).upper()
        cid = str(uuid.uuid4()).upper()

        v = json.loads(json.dumps(tmpl_video))
        v["id"] = vid
        v["path"] = path
        v["material_name"] = P(path).name
        v["duration"] = DUR
        new_videos.append(v)

        new_speeds.append({"curve_speed": None, "id": sid, "mode": 0, "speed": 1.0, "type": "speed"})

        # 每条片段独立背景画布；片段 refs 第二位绑定 canvas（与可正常打开的草稿基线一致）
        refs = [sid]
        if tmpl_canvas:
            cv = json.loads(json.dumps(tmpl_canvas))
            cv["id"] = cid
            new_canvases.append(cv)
            refs.append(cid)

        s = json.loads(json.dumps(tmpl_seg))
        s["id"] = str(uuid.uuid4()).upper()
        s["material_id"] = vid
        s["source_timerange"] = {"duration": DUR, "start": 0}
        s["target_timerange"] = {"duration": DUR, "start": cur}
        s["extra_material_refs"] = refs
        new_segments.append(s)
        cur += DUR

    # 所有片段排在同一条视频轨道上，按顺序首尾相接（一行时间线）
    track = json.loads(json.dumps(tmpl_track))
    track["id"] = str(uuid.uuid4()).upper()
    track["segments"] = new_segments

    d["materials"]["videos"] = new_videos
    d["materials"]["speeds"] = new_speeds
    d["materials"]["canvases"] = new_canvases
    d["materials"]["audio_balances"] = []
    d["tracks"] = [track]
    d["duration"] = cur
    d["name"] = draft_name
    json.dump(d, open(info_path, "w"), ensure_ascii=False)

    # 更新meta
    meta["draft_name"] = draft_name
    meta["draft_fold_path"] = str(new_draft)
    meta["draft_materials"][0]["value"] = []
    for shot_no, path in clips:
        meta["draft_materials"][0]["value"].append({
            "duration": DUR, "extra_info": P(path).name, "file_Path": path,
            "height": 720, "md5": "", "metetype": "video",
            "roughcut_time_range": {"duration": DUR, "start": 0}, "type": 0, "width": 1280
        })
    json.dump(meta, open(meta_path, "w"), ensure_ascii=False)

    # 打开剪映（替身模式下不拉起桌面应用）
    if not fake.enabled():
        subprocess.Popen(["open", "-a", "VideoFusion-macOS"])

    msg = f"已导出{len(clips)}个视频到剪映草稿「{draft_name}」"
    if skipped_hevc:
        msg += f"；已跳过 {len(skipped_hevc)} 条 H.265 素材（镜号 {', '.join(str(x) for x in skipped_hevc)}），需重跑成 H.264"
    return {"ok": True, "msg": msg, "draft": draft_name}
