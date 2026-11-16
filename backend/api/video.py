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
from core.doubao_automation import (DoubaoVideoGenerator, normalize_proxy, to_unwatermarked_url,
                                    _detect_codec_fourcc, _HEVC_MARKS)
from core.doubao_chrome import (DOUBAO_CHAT_URL, LoginCheckError, check_account_login,
                                ensure_debug_port, inject_cookies_into_chrome, launch_chrome,
                                probe_debug_port, profile_lock_pid)
from core.providers import fake
from core.video_models import get_video_model
from core.video_prompt import build_upload_plan
from core.style_library import build_video_style_line, medium_key, style_mismatch_warnings, style_ref
from core.script_text import scene_location_of
from core.ffmpeg_tool import grab_last_frame
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
                           static_dir, use_prev_frame: bool = True) -> dict:
    """一次视频生成的任务：参考图（按上传顺序）+ 提示词 + 模型与时长。

    用哪些资产、什么顺序由 core.asset_binding.collect_bindings 决定（剧本场次地点参与场景归属）；
    参考图上传顺序与提示词里的 refN 链接由 core.video_prompt.build_upload_plan 用同一个列表产出。
    视频段（有 lines）按五段结构组装提示词；旧格式分镜照旧发 video_prompt 原文。
    """
    params = video_task_params(shot, project)
    model = get_video_model(params["model_key"])
    extra_refs = []
    prev_frame = {"attached": False, "image": None, "reason": None}
    # 上一条已成片就截尾帧传给本条做开场首帧参考；上一条未成片（如并行批量）才跳过。
    if use_prev_frame:
        shot_no = shot["shot_no"]
        prev_shot = await db.shots.find_one({"project_id": shot["project_id"], "shot_no": shot_no - 1})
        if not prev_shot:
            prev_frame["reason"] = "首段无上一段尾帧"
        elif not prev_shot.get("video_path"):
            prev_frame["reason"] = "上一段分镜尚未成片"
        else:
            prev_vid = static_dir / prev_shot["video_path"]
            if not prev_vid.exists():
                prev_frame["reason"] = "上一段成片文件缺失"
            else:
                frame_name = f"prev_frame_shot{shot_no}.png"
                frame_path = static_dir / "images" / frame_name
                if grab_last_frame(prev_vid, frame_path):
                    extra_refs.append({"type": "关键帧", "name": "上一段尾帧", "path": str(frame_path)})
                    prev_frame = {"attached": True, "image": f"images/{frame_name}", "reason": None}
                    logger.info(f"分镜{shot_no} 已添加上一段关键帧: {frame_name}")
                else:
                    prev_frame["reason"] = "尾帧截帧失败"
    plan = build_upload_plan(shot, chars, scenes, props, static_dir, model,
                             scene_location=await scene_location_of(db, shot), extra_refs=extra_refs,
                             genre=str((project or {}).get("genre") or ""),
                             style_suffix=build_video_style_line(**style_ref(project)))
    style_warnings = style_mismatch_warnings(plan["refs"], list(chars) + list(scenes) + list(props),
                                             medium_key(**style_ref(project)))
    if not prev_frame["attached"]:
        plan["warnings"].append(f"本条未带上一段尾帧参考：{prev_frame['reason']}")
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
        "prev_frame": prev_frame,
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

    account_type = data.get("account_type", "free")
    if account_type not in pool.ACCOUNT_TYPES:
        raise HTTPException(status_code=400, detail="账号类型只能是 member（额度会员）或 free（免费）")

    # 自动生成 profile 目录
    existing_ids = [a["id"] for a in pool.accounts]
    idx = 1
    while f"account_{idx}" in existing_ids:
        idx += 1
    profile_dir = f".doubao_profiles/account_{idx}"

    proxy = normalize_proxy(data.get("proxy"))

    new_account = {
        "id": f"account_{idx}",
        "name": name,
        "profile_dir": profile_dir,
        "account_type": account_type,
        "cookies": [],
        "enabled": True,
        "logged_in": False,
        "proxy": proxy,
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
    if "proxy" in data:
        patch["proxy"] = normalize_proxy(data.get("proxy"))

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


@router.put("/accounts/{account_id}/type")
async def set_account_type(account_id: str, body: dict, user: dict = Depends(get_current_user)):
    """切换账号计费类型：member=按套餐额度，free=每日限额。"""
    pool = DoubaoAccountPool()
    account = pool.get_account_by_id(account_id)
    if not account:
        raise HTTPException(status_code=404, detail="账号不存在")

    account_type = body.get("account_type")
    if account_type not in pool.ACCOUNT_TYPES:
        raise HTTPException(status_code=400, detail="账号类型只能是 member（额度会员）或 free（免费）")

    pool.set_account_type(account_id, account_type)
    label = "额度会员" if account_type == "member" else "免费"
    return ResponseModel(message=f"已切换为{label}账号")


@router.post("/generate/batch")
async def generate_batch_videos(
    project_id: str,
    shot_ids: Optional[List[str]] = None,
    parallel: bool = False,
    limit: int = 0,
    use_prev_frame: bool = True,
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
        tasks.append(await build_video_task(db, shot, project, all_chars, all_scenes, all_props, static_dir,
                                            use_prev_frame=use_prev_frame))

    # ===== 并行模式：多账号并发，每个账号一个独立生成器、组内开多标签页 =====
    if parallel:
        pool = DoubaoAccountPool()
        total_quota = pool.get_total_available_quota()
        if total_quota < len(tasks):
            raise HTTPException(
                status_code=400,
                detail=f"额度不足：需要 {len(tasks)} 条，各账号本批最多可生成 {total_quota} 条"
            )

        allocation = pool.allocate_parallel(len(tasks))
        if not allocation:
            raise HTTPException(status_code=400, detail="没有可用的豆包账号")

        # 按归属分组准备任务（tasks 下标即 allocate_parallel 的 task_indices）
        group_plan = [(alloc, [tasks[i] for i in alloc["task_indices"]])
                      for alloc in allocation]
        logger.info("并行多账号分摊: %s",
                    [(a["account_name"], len(g)) for a, g in group_plan])

        def build_on_ready(alloc):
            # 每个视频下好就立刻写库，并按归属账号扣今日用量
            async def _write(shot_id, shot_no, video_path):
                await db.shots.update_one(
                    {"_id": ObjectId(shot_id)},
                    {"$set": {"video_path": video_path, "status": "done"}}
                )
                logger.info(f"分镜 {shot_no} video_path 已写入: {video_path}")

            def on_ready_sync(shot_id, shot_no, video_path, frame=""):
                asyncio.run_coroutine_threadsafe(
                    _write(shot_id, shot_no, video_path), loop).result(timeout=30)
                pool.increment_usage(alloc["account_id"])
            return on_ready_sync

        def run_group(alloc, gtasks):
            # 每个账号独立 generator：独立浏览器 context 与页面状态，组间互不干扰
            gen = DoubaoVideoGenerator(str(PROJECT_ROOT), status_callback=sse_status_callback)
            rec = {"account_id": alloc["account_id"], "account_name": alloc["account_name"],
                   "success": [], "failed": [], "videos": {}, "error": None}
            try:
                res = gen.generate_parallel(
                    profile_dir=alloc.get("profile_dir", ""),
                    cookies=alloc.get("cookies", []),
                    proxy=alloc.get("proxy"),
                    tasks=gtasks,
                    max_parallel=len(gtasks),
                    on_video_ready=build_on_ready(alloc),
                )
                rec["success"] = res["success"]
                rec["failed"] = res["failed"]
                rec["videos"] = res["videos"]
                # 回写最新 cookie（续期）与额度读数 / 单条成本
                if gen.last_cookies:
                    pool.set_cookies(alloc["account_id"], gen.last_cookies)
                pool.save_generation_quota(alloc["account_id"], gen)
            except Exception as e:
                logger.error("账号 %s 并行生成失败: %s", alloc["account_name"], e)
                rec["error"] = str(e)
                rec["failed"] = [t.get("shot_no") for t in gtasks
                                 if t.get("shot_no") not in rec["success"]]
            return rec

        from concurrent.futures import ThreadPoolExecutor, as_completed

        def _run_parallel():
            collected = []
            with ThreadPoolExecutor(max_workers=len(group_plan)) as ex:
                futures = {ex.submit(run_group, alloc, gt): alloc for alloc, gt in group_plan}
                for f in as_completed(futures):
                    collected.append(f.result())
            return collected

        # 阻塞等待必须移出事件循环：否则主 loop 被占住，回写库与 SSE 回调调度不到，页面也无响应
        results = await run_in_threadpool(_run_parallel)

        success_count = sum(len(r["success"]) for r in results)
        failed_count = sum(len(r["failed"]) for r in results)
        videos = {}
        for r in results:
            videos.update(r["videos"])

        # 兜底：线程内回调写库若超时失败，整批结束后按 videos 映射统一补挂视频
        task_by_no = {t["shot_no"]: t for t in tasks}
        for r in results:
            for sn, vp in (r.get("videos") or {}).items():
                if not vp:
                    continue
                task = task_by_no.get(sn)
                if not task:
                    continue
                await db.shots.update_one(
                    {"_id": ObjectId(task["shot_id"])},
                    {"$set": {"video_path": vp, "status": "done"}})

        return ResponseModel(data={
            "total_shots": len(tasks),
            "success_count": success_count,
            "failed_count": failed_count,
            "results": [{
                "account_name": r["account_name"],
                "success_count": len(r["success"]),
                "failed_count": len(r["failed"]),
            } for r in results],
            "videos": videos,
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
        tasks = [await build_video_task(db, shots[idx], project, all_chars, all_scenes, all_props, static_dir,
                                        use_prev_frame=use_prev_frame)
                 for idx in task_indices]
        
        logger.info(f"账号 {account_name} 分配任务: {len(tasks)} 条")
        
        # 执行生成
        try:
            generator = DoubaoVideoGenerator(str(PROJECT_ROOT), status_callback=sse_status_callback)
            result = await run_in_threadpool(
                generator.generate_batch,
                profile_dir=profile_dir,
                cookies=alloc_cookies,
                proxy=alloc.get("proxy"),
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
                "failed_reasons": {
                    str(k): {
                        "code": v.get("code", ""),
                        "msg": v.get("msg", ""),
                        "reason": v.get("detail", "") or v.get("msg", ""),
                        "conversation_url": v.get("conversation_url", ""),
                    } for k, v in result.get("reasons", {}).items()
                },
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
    use_prev_frame: bool = True,
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
        static_dir, use_prev_frame=use_prev_frame)
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
            proxy=account.get("proxy"),
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
            fail_msg = fail.get("msg") or "生成失败"
            fail_detail = fail.get("detail")
            if fail_detail and fail_detail not in fail_msg:
                fail_msg = f"{fail_msg}：{fail_detail}"
            raise Exception(fail_msg)
            
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
        clips.append((s["shot_no"], str(fpath.resolve()), s))

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

    # 素材拷进草稿自有 Resources/：剪映对草稿目录内文件不走外部安全书签，
    # 避免外部路径首次建书签失败 code 256（media missing / 误报格式不支持）。
    res_dir = new_draft / "Resources"
    res_dir.mkdir(exist_ok=True)

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

    new_videos, new_speeds, new_canvases, new_segments, inner_clips = [], [], [], [], []
    cur = 0
    for shot_no, path, shot in clips:
        vid = str(uuid.uuid4()).upper()
        sid = str(uuid.uuid4()).upper()
        cid = str(uuid.uuid4()).upper()

        # 拷贝进草稿自有 Resources/，写草稿内绝对路径；剪映对草稿内文件不走外部安全书签
        src = P(path)
        dst = res_dir / src.name
        if dst.exists() and dst.stat().st_size != src.stat().st_size:
            import hashlib
            dst = res_dir / (hashlib.md5(src.read_bytes()).hexdigest()[:8] + "_" + src.name)
        shutil.copy2(src, dst)
        inner = str(dst)

        v = json.loads(json.dumps(tmpl_video))
        v["id"] = vid
        v["path"] = inner
        v["material_name"] = src.name
        v["duration"] = DUR
        new_videos.append(v)
        inner_clips.append((shot_no, inner, src.name))

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

    # 导出前现场离线识别整集字幕，写一条底部文字轨；每次导出重新识别，不提前固化
    from core.draft_subtitle import collect_entries, build_jianying
    sub_entries = collect_entries([(shot, path) for _, path, shot in clips], DUR / 1_000_000)
    sub = build_jianying(sub_entries)
    d["materials"]["texts"] = sub["texts"]
    d["materials"].setdefault("material_animations", []).extend(sub["animations"])
    d["tracks"].append(sub["text_track"])

    d["duration"] = cur
    d["name"] = draft_name
    json.dump(d, open(info_path, "w"), ensure_ascii=False)

    # 更新meta
    meta["draft_name"] = draft_name
    meta["draft_fold_path"] = str(new_draft)
    meta["draft_materials"][0]["value"] = []
    for shot_no, inner, name in inner_clips:
        meta["draft_materials"][0]["value"].append({
            "duration": DUR, "extra_info": name, "file_Path": inner,
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


@router.get("/export/capcut")
async def export_capcut(project_id: str, video_set_id: str = "", user: dict = Depends(get_current_user)):
    """一键导出到国际版 CapCut：写草稿并打开 CapCut"""
    import json, uuid, subprocess, time, shutil, hashlib, platform
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
            logger.warning("导出 CapCut 草稿跳过 H.265/HEVC 素材 shot=%s %s", s["shot_no"], vp)
            skipped_hevc.append(s["shot_no"])
            continue
        clips.append((s["shot_no"], str(fpath.resolve()), s))

    if not clips:
        return {"ok": False, "msg": "没有可导入 CapCut 的视频（现有素材为 H.265，需先转码或重跑成 H.264）"}

    from config.settings import settings
    if settings.CAPCUT_DRAFT_DIR:
        draft_root = P(settings.CAPCUT_DRAFT_DIR).expanduser()
    else:
        system = platform.system()
        if system == "Windows":
            draft_root = P.home() / "AppData/Local/CapCut/User Data/Projects/com.lveditor.draft"
        else:
            draft_root = P.home() / "Movies/CapCut/User Data/Projects/com.lveditor.draft"
    if not draft_root.exists():
        return {"ok": False, "msg": f"找不到 CapCut 草稿目录: {draft_root}"}

    template_dir = (P(settings.CAPCUT_TEMPLATE_DIR).expanduser() if settings.CAPCUT_TEMPLATE_DIR
                    else P(__file__).parent.parent / ".capcut_template")
    if not (template_dir / "draft_info.json").exists():
        return {"ok": False, "msg": "找不到 CapCut 模板草稿，请先在 CapCut 手动建一个含视频的草稿"}

    ts = int(time.time())
    draft_name = f"{project_name}_{ts}"
    new_draft = draft_root / draft_name
    if new_draft.exists():
        shutil.rmtree(new_draft)
    shutil.copytree(template_dir, new_draft)

    # 素材拷进草稿自有 Resources/：CapCut 对草稿目录内文件不走外部安全书签，避免外部路径建书签失败
    res_dir = new_draft / "Resources"
    res_dir.mkdir(exist_ok=True)

    info_path = new_draft / "draft_info.json"
    meta_path = new_draft / "draft_meta_info.json"
    d = json.load(open(info_path))
    meta = json.load(open(meta_path))

    tmpl_video = d["materials"]["videos"][0]
    tmpl_seg = d["tracks"][0]["segments"][0]
    tmpl_track = d["tracks"][0]
    tmpl_speed = d["materials"]["speeds"][0]
    tmpl_placeholder = d["materials"]["placeholder_infos"][0] if d["materials"].get("placeholder_infos") else None
    tmpl_canvas = d["materials"]["canvases"][0] if d["materials"].get("canvases") else None
    tmpl_sound = d["materials"]["sound_channel_mappings"][0] if d["materials"].get("sound_channel_mappings") else None
    tmpl_vocal = d["materials"]["vocal_separations"][0] if d["materials"].get("vocal_separations") else None
    DUR = tmpl_seg["target_timerange"]["duration"]

    new_videos, new_speeds, new_placeholders, new_canvases, new_sounds, new_vocals, new_segments = [], [], [], [], [], [], []
    inner_clips = []
    cur = 0
    now_s = int(time.time())
    now_us = int(time.time() * 1_000_000)
    for shot_no, path, shot in clips:
        vid = str(uuid.uuid4()).upper()
        lid = str(uuid.uuid4()).lower()
        sid = str(uuid.uuid4()).upper()
        pid = str(uuid.uuid4()).upper()
        cid = str(uuid.uuid4()).upper()
        aid = str(uuid.uuid4()).upper()
        vid2 = str(uuid.uuid4()).upper()
        segid = str(uuid.uuid4()).upper()

        src = P(path)
        dst = res_dir / src.name
        if dst.exists() and dst.stat().st_size != src.stat().st_size:
            dst = res_dir / (hashlib.md5(src.read_bytes()).hexdigest()[:8] + "_" + src.name)
        shutil.copy2(src, dst)
        inner = str(dst)

        v = json.loads(json.dumps(tmpl_video))
        v["id"] = vid
        v["local_material_id"] = lid
        v["path"] = inner
        v["material_name"] = src.name
        v["duration"] = DUR
        new_videos.append(v)

        speed = json.loads(json.dumps(tmpl_speed))
        speed["id"] = sid
        new_speeds.append(speed)

        refs = [sid]
        if tmpl_placeholder:
            ph = json.loads(json.dumps(tmpl_placeholder))
            ph["id"] = pid
            new_placeholders.append(ph)
            refs.append(pid)
        if tmpl_canvas:
            cv = json.loads(json.dumps(tmpl_canvas))
            cv["id"] = cid
            new_canvases.append(cv)
            refs.append(cid)
        if tmpl_sound:
            sd = json.loads(json.dumps(tmpl_sound))
            sd["id"] = aid
            new_sounds.append(sd)
            refs.append(aid)
        if tmpl_vocal:
            vc = json.loads(json.dumps(tmpl_vocal))
            vc["id"] = vid2
            new_vocals.append(vc)
            refs.append(vid2)

        s = json.loads(json.dumps(tmpl_seg))
        s["id"] = segid
        s["material_id"] = vid
        s["source_timerange"] = {"duration": DUR, "start": 0}
        s["target_timerange"] = {"duration": DUR, "start": cur}
        s["extra_material_refs"] = refs
        new_segments.append(s)
        inner_clips.append((lid, inner, src.name))
        cur += DUR

    track = json.loads(json.dumps(tmpl_track))
    track["id"] = str(uuid.uuid4()).upper()
    track["segments"] = new_segments

    d["id"] = str(uuid.uuid4()).upper()
    d["materials"]["videos"] = new_videos
    d["materials"]["speeds"] = new_speeds
    d["materials"]["placeholder_infos"] = new_placeholders
    d["materials"]["canvases"] = new_canvases
    d["materials"]["sound_channel_mappings"] = new_sounds
    d["materials"]["vocal_separations"] = new_vocals
    d["tracks"] = [track]

    # 导出前现场离线识别整集字幕，写一条底部文字轨；每次导出重新识别，不提前固化
    from core.draft_subtitle import collect_entries, build_capcut
    sub_entries = collect_entries([(shot, path) for _, path, shot in clips], DUR / 1_000_000)
    sub = build_capcut(sub_entries)
    d["materials"]["texts"] = sub["texts"]
    d["materials"].setdefault("material_animations", []).extend(sub["animations"])
    d["tracks"].append(sub["text_track"])

    d["duration"] = cur
    d["name"] = draft_name
    json.dump(d, open(info_path, "w"), ensure_ascii=False)

    # 更新 meta
    meta["draft_id"] = str(uuid.uuid4()).upper()
    meta["draft_name"] = draft_name
    meta["draft_fold_path"] = str(new_draft)
    meta["draft_materials"][0]["value"] = []
    for lid, inner, name in inner_clips:
        meta["draft_materials"][0]["value"].append({
            "create_time": now_s,
            "duration": DUR,
            "extra_info": name,
            "file_Path": inner,
            "height": 720,
            "id": lid,
            "import_time": now_s,
            "import_time_ms": now_us,
            "item_source": 1,
            "md5": "",
            "metetype": "video",
            "roughcut_time_range": {"duration": DUR, "start": 0},
            "sub_time_range": {"duration": -1, "start": -1},
            "type": 0,
            "width": 1280,
        })
    meta["tm_duration"] = cur
    meta["tm_draft_create"] = now_us
    meta["tm_draft_modified"] = now_us
    json.dump(meta, open(meta_path, "w"), ensure_ascii=False)

    # 清掉模板/旧素材残留的本地缓存附属文件，避免旧 id 引用
    kv_path = new_draft / "key_value.json"
    if kv_path.exists():
        json.dump({}, open(kv_path, "w"), ensure_ascii=False)
    vs_path = new_draft / "draft_virtual_store.json"
    if vs_path.exists():
        json.dump({
            "draft_materials": [],
            "draft_virtual_store": [
                {"type": 0, "value": []},
                {"type": 1, "value": [{"child_id": lid, "parent_id": ""} for lid, _, _ in inner_clips]},
                {"type": 2, "value": []},
            ],
        }, open(vs_path, "w"), ensure_ascii=False)

    # 在 CapCut 草稿根索引登记新草稿，否则草稿列表可能不显示
    root_index = draft_root / "root_meta_info.json"
    if root_index.exists():
        try:
            root_meta = json.load(open(root_index))
        except Exception:
            root_meta = {"all_draft_store": [], "draft_ids": 0, "root_path": str(draft_root)}
    else:
        root_meta = {"all_draft_store": [], "draft_ids": 0, "root_path": str(draft_root)}
    store = root_meta.setdefault("all_draft_store", [])
    store = [x for x in store if x.get("draft_fold_path") != str(new_draft)]
    store.append({
        "draft_cloud_last_action_download": False,
        "draft_cloud_purchase_info": "",
        "draft_cloud_template_id": "",
        "draft_cloud_tutorial_info": "",
        "draft_cloud_videocut_purchase_info": "",
        "draft_cover": str(new_draft / "draft_cover.jpg"),
        "draft_fold_path": str(new_draft),
        "draft_id": meta["draft_id"],
        "draft_is_ai_shorts": False,
        "draft_is_invisible": False,
        "draft_json_file": str(info_path),
        "draft_name": draft_name,
        "draft_new_version": "",
        "draft_root_path": str(draft_root),
        "draft_timeline_materials_size": meta.get("draft_timeline_materials_size_", 0),
        "draft_type": "",
        "tm_draft_cloud_completed": "",
        "tm_draft_cloud_modified": 0,
        "tm_draft_create": meta["tm_draft_create"],
        "tm_draft_modified": meta["tm_draft_modified"],
        "tm_draft_removed": 0,
        "tm_duration": cur,
    })
    root_meta["all_draft_store"] = store
    root_meta["draft_ids"] = len(store)
    json.dump(root_meta, open(root_index, "w"), ensure_ascii=False)

    # 打开 CapCut（替身模式下不拉起桌面应用）
    if not fake.enabled():
        subprocess.Popen(["open", "-a", "CapCut"])

    msg = f"已导出{len(clips)}个视频到 CapCut 草稿「{draft_name}」"
    if skipped_hevc:
        msg += f"；已跳过 {len(skipped_hevc)} 条 H.265 素材（镜号 {', '.join(str(x) for x in skipped_hevc)}），需重跑成 H.264"
    return {"ok": True, "msg": msg, "draft": draft_name}
