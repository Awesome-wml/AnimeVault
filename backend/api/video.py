"""视频生成API（豆包自动化）"""
from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks, UploadFile, File
from starlette.concurrency import run_in_threadpool
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

# SSE事件队列：project_id -> 队列
import asyncio
sse_queues: dict[str, asyncio.Queue] = {}

async def push_sse(project_id: str, event: dict):
    """向指定项目的SSE队列推送事件"""
    q = sse_queues.get(project_id)
    if q:
        await q.put(event)

@router.get("/events/{project_id}")
async def sse_events(project_id: str):
    """SSE推送：视频生成完成等事件"""
    from sse_starlette.sse import EventSourceResponse
    q = asyncio.Queue()
    sse_queues[project_id] = q
    
    async def event_generator():
        try:
            while True:
                msg = await q.get()
                yield {"event": "message", "data": str(msg)}
        finally:
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
                "daily_limit": pool.DAILY_LIMIT
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
        accounts = [pool.annotate(dict(acc)) for acc in pool.accounts]
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
    
    # 自动打开 Chrome 让用户登录（用系统命令，独立窗口不随请求关闭）
    import subprocess
    profile_path = str(PROJECT_ROOT / profile_dir)
    os.makedirs(profile_path, exist_ok=True)
    chrome_path = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    subprocess.Popen([
        chrome_path,
        f"--user-data-dir={profile_path}",
        "--password-store=basic",
        "--use-mock-keychain",
        "https://www.doubao.com/chat/"
    ])
    return ResponseModel(
        message=f"账号 '{name}' 已创建，Chrome 已打开，请在浏览器中登录豆包，登录成功后点「检查登录」",
        data={"account": new_account}
    )


@router.post("/accounts/{account_id}/check-login")
async def check_login(account_id: str, user: dict = Depends(get_current_user)):
    """检查登录状态：优先用数据库 cookie 验证；成功后回写最新 cookie。未登录则弹出 Chrome 扫码。"""
    pool = DoubaoAccountPool()
    account = pool.get_account_by_id(account_id)
    if not account:
        raise HTTPException(status_code=404, detail="账号不存在")

    from core.doubao_automation import DoubaoVideoGenerator
    generator = DoubaoVideoGenerator(str(PROJECT_ROOT))
    stored_cookies = account.get("cookies") or []

    def _do_check():
        # 有 cookie 走无目录 context；无 cookie 走临时持久化目录（首次扫码）
        if stored_cookies:
            p, ctx, page = generator.connect_with_cookies(stored_cookies, headless=False)
        else:
            p, ctx, page = generator.connect_to_profile(account["profile_dir"], headless=False)
        try:
            page.goto("https://www.doubao.com/chat/", wait_until="domcontentloaded")
            page.wait_for_timeout(5000)
            login_btn = page.query_selector('button:has-text("登录")')
            logged_in = login_btn is None
            fresh_cookies = DoubaoVideoGenerator.export_cookies(ctx) if logged_in else []
            return logged_in, fresh_cookies
        finally:
            try:
                ctx.close()
            except Exception:
                pass
            try:
                p.stop()
            except Exception:
                pass

    try:
        logged_in, fresh_cookies = await run_in_threadpool(_do_check)

        if logged_in:
            # 回写最新 cookie 到数据库（续期）
            pool.set_cookies(account_id, fresh_cookies)
            return ResponseModel(message="✅ 已登录，登录态已保存")

        pool.set_login_state(account_id, False)
        # 未登录，弹出 Chrome 让用户在临时目录扫码
        import subprocess
        profile_path = str(PROJECT_ROOT / account["profile_dir"])
        os.makedirs(profile_path, exist_ok=True)
        chrome_path = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
        subprocess.Popen([
            chrome_path,
            f"--user-data-dir={profile_path}",
            "--password-store=basic",
            "--use-mock-keychain",
            "https://www.doubao.com/chat/"
        ])
        return ResponseModel(message="未登录，已弹出 Chrome，请登录豆包，登录完成后再点一次检查")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"检查失败: {e}")


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
    static_dir = PROJECT_ROOT / "static"
    all_chars = await db.characters.find({"project_id": project_id}).to_list(None)
    all_scenes = await db.scenes.find({"project_id": project_id}).to_list(None)
    all_props = await db.props.find({"project_id": project_id}).to_list(None)

    tasks = []
    for shot in shots:
        assets = []
        if shot.get("img_path"):
            p = static_dir / shot["img_path"]
            if p.exists():
                assets.append(str(p))
        shot_text = (shot.get("text", "") + " " + shot.get("video_prompt", ""))
        for ch in all_chars:
            if ch.get("name") and ch["name"] in shot_text and ch.get("image_path"):
                f = static_dir / ch["image_path"]
                if f.exists() and str(f) not in assets:
                    assets.append(str(f))
        for sc in all_scenes:
            if sc.get("name") and sc["name"] in shot_text and sc.get("image_path"):
                f = static_dir / sc["image_path"]
                if f.exists() and str(f) not in assets:
                    assets.append(str(f))
        for pr in all_props:
            if pr.get("name") and pr["name"] in shot_text:
                img = pr.get("image_path") or pr.get("img_path")
                if img:
                    f = static_dir / img
                    if f.exists() and str(f) not in assets:
                        assets.append(str(f))
        # 上一位关键帧：用户开启才截
        if shot.get("use_prev_frame"):
            prev_shot = await db.shots.find_one(
                {"project_id": project_id, "shot_no": shot_no - 1}
            )
            if prev_shot and prev_shot.get("video_path"):
                import subprocess
                prev_vid = static_dir / prev_shot["video_path"]
                if prev_vid.exists():
                    frame_name = f"prev_frame_shot{shot_no}.png"
                    frame_path = static_dir / "images" / frame_name
                    frame_path.parent.mkdir(exist_ok=True)
                    subprocess.run(
                        ["ffmpeg", "-y", "-sseof", "-0.5", "-i", str(prev_vid),
                         "-frames:v", "1", str(frame_path)],
                        capture_output=True, timeout=15
                    )
                    if frame_path.exists():
                        assets.append(str(frame_path))
                        logger.info(f"分镜{shot_no} 已添加上一位关键帧: {frame_name}")
        tasks.append({
            "shot_id": str(shot["_id"]),
            "shot_no": shot["shot_no"],
            "prompt": shot.get("video_prompt") or shot.get("prompt", ""),
            "text": shot.get("text", ""),
            "assets": assets,
        })

    # ===== 并行模式：一个账号开多 page =====
    if parallel:
        pool = DoubaoAccountPool()
        acc = pool.get_available_account()
        if not acc:
            raise HTTPException(status_code=400, detail="没有可用的豆包账号")
        logger.info(f"并行模式：账号 {acc['name']}，{len(tasks)} 条任务")
        
        # SSE状态推送回调
        async def push_status_async(data):
            await push_sse(project_id, data)
        def status_callback(data):
            asyncio.run_coroutine_threadsafe(push_status_async(data), loop)
        
        generator = DoubaoVideoGenerator(str(PROJECT_ROOT), status_callback=status_callback)

        # 每个视频下好就立刻写库
        async def on_ready(shot_id, shot_no, video_path):
            await db.shots.update_one(
                {"_id": ObjectId(shot_id)},
                {"$set": {"video_path": video_path, "status": "done"}}
            )
            logger.info(f"分镜 {shot_no} video_path 已写入: {video_path}")

        import asyncio
        loop = asyncio.get_event_loop()
        def on_ready_sync(shot_id, shot_no, video_path, frame=""):
            asyncio.run_coroutine_threadsafe(on_ready(shot_id, shot_no, video_path), loop)

        result = await run_in_threadpool(
            generator.generate_parallel,
            profile_dir=acc.get("profile_dir", ""),
            cookies=acc.get("cookies", []),
            tasks=tasks,
            max_parallel=min(5, len(tasks)),
            on_video_ready=on_ready_sync,
        )
        # 回写最新 cookie（续期）
        if generator.last_cookies:
            pool.set_cookies(acc["id"], generator.last_cookies)
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
            detail=f"配额不足：需要 {len(shots)} 条，今日剩余 {total_quota} 条"
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
        tasks = []
        # 预加载项目所有角色/场景/道具
        all_chars = await db.characters.find({"project_id": project_id}).to_list(None)
        all_scenes = await db.scenes.find({"project_id": project_id}).to_list(None)
        all_props = await db.props.find({"project_id": project_id}).to_list(None)

        for idx in task_indices:
            shot = shots[idx]

            # 收集资产文件路径
            assets = []

            # 添加分镜参考图
            if shot.get("img_path"):
                img_full_path = static_dir / shot["img_path"]
                if img_full_path.exists():
                    assets.append(str(img_full_path))

            # 添加涉及的角色图
            shot_text = (shot.get("text", "") + " " + shot.get("video_prompt", ""))
            for ch in all_chars:
                ch_name = ch.get("name", "")
                if ch_name and ch_name in shot_text:
                    img = ch.get("image_path")
                    if img:
                        full = static_dir / img
                        if full.exists() and str(full) not in assets:
                            assets.append(str(full))

            # 添加场景图
            for sc in all_scenes:
                sc_name = sc.get("name", "")
                if sc_name and sc_name in shot_text:
                    img = sc.get("image_path")
                    if img:
                        full = static_dir / img
                        if full.exists() and str(full) not in assets:
                            assets.append(str(full))

            # 添加道具图
            for pr in all_props:
                pr_name = pr.get("name", "")
                if pr_name and pr_name in shot_text:
                    img = pr.get("image_path") or pr.get("img_path")
                    if img:
                        full = static_dir / img
                        if full.exists() and str(full) not in assets:
                            assets.append(str(full))

            # 添加音频
            if shot.get("audio_path"):
                audio_full_path = static_dir / shot["audio_path"]
                if audio_full_path.exists():
                    assets.append(str(audio_full_path))

            tasks.append({
                "shot_id": str(shot["_id"]),
                "shot_no": shot["shot_no"],
                "prompt": shot.get("video_prompt") or shot.get("prompt", ""),
                "text": shot.get("text", ""),
                "assets": assets
            })
        
        logger.info(f"账号 {account_name} 分配任务: {len(tasks)} 条")
        
        # 执行生成
        try:
            generator = DoubaoVideoGenerator(str(PROJECT_ROOT))
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
                "failed_shots": result["failed"]
            })

            # 回写最新 cookie（续期）
            if generator.last_cookies:
                pool.set_cookies(account_id, generator.last_cookies)

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

    # 1. 分镜自身参考图
    if shot.get("img_path"):
        img_full_path = static_dir / shot["img_path"]
        if img_full_path.exists():
            assets.append(str(img_full_path))

    # 2. 该分镜涉及的角色图（从text/video_prompt里提取角色名）
    shot_text = (shot.get("text", "") + " " + shot.get("video_prompt", ""))
    chars = await db.characters.find({"project_id": shot["project_id"]}).to_list(None)
    for ch in chars:
        ch_name = ch.get("name", "")
        if ch_name and ch_name in shot_text:
            img = ch.get("image_path")
            if img:
                full = static_dir / img
                if full.exists() and str(full) not in assets:
                    assets.append(str(full))
                    logger.info(f"  角色图: {ch_name} -> {img}")

    # 3. 场景图
    scenes = await db.scenes.find({"project_id": shot["project_id"]}).to_list(None)
    for sc in scenes:
        sc_name = sc.get("name", "")
        if sc_name and sc_name in shot_text:
            img = sc.get("image_path")
            if img:
                full = static_dir / img
                if full.exists() and str(full) not in assets:
                    assets.append(str(full))
                    logger.info(f"  场景图: {sc_name} -> {img}")

    # 4. 道具图
    props = await db.props.find({"project_id": shot["project_id"]}).to_list(None)
    for pr in props:
        pr_name = pr.get("name", "")
        if pr_name and pr_name in shot_text:
            img = pr.get("image_path") or pr.get("img_path")
            if img:
                full = static_dir / img
                if full.exists() and str(full) not in assets:
                    assets.append(str(full))
                    logger.info(f"  道具图: {pr_name} -> {img}")

    if shot.get("audio_path"):
        audio_full_path = static_dir / shot["audio_path"]
        if audio_full_path.exists():
            assets.append(str(audio_full_path))

    logger.info(f"  共 {len(assets)} 个素材文件")
    
    task = {
        "shot_id": str(shot["_id"]),
        "shot_no": shot["shot_no"],
        "prompt": shot.get("video_prompt") or shot.get("prompt", ""),
        "text": shot.get("text", ""),
        "assets": assets
    }
    
    # 执行生成
    try:
        logger.info(f"开始生成: shot_id={shot_id}, account={account['name']}, cookies={len(account.get('cookies', []))} 个")
        generator = DoubaoVideoGenerator(str(PROJECT_ROOT))
        logger.info("正在启动 Chrome...")
        result = await run_in_threadpool(
            generator.generate_batch,
            profile_dir=account.get("profile_dir", ""),
            cookies=account.get("cookies", []),
            tasks=[task],
            interval=1
        )
        logger.info(f"生成完成: {result}")
        
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
            raise Exception("生成失败")
            
    except Exception as e:
        logger.error(f"单条生成失败: {e}")
        raise HTTPException(status_code=500, detail=f"生成失败: {str(e)}")


# ===== 手动补录视频（自动化抓取失败时，人工上传文件 / 粘贴直链）=====
VIDEO_EXTS = {".mp4", ".mov", ".webm", ".m4v", ".mkv"}


def _save_video_bytes(shot_no: int, data: bytes, ext: str) -> str:
    """把视频字节存到 static/videos，返回相对路径 videos/xxx.ext。"""
    import time as _time
    videos_dir = PROJECT_ROOT / "static" / "videos"
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
    """在系统 Chrome 打开豆包页面（人工排查 / 手动下载视频用）。"""
    pool = DoubaoAccountPool()
    account = pool.get_account_by_id(account_id)
    if not account:
        raise HTTPException(status_code=404, detail="账号不存在")

    import subprocess
    target_url = (body or {}).get("url") or "https://www.doubao.com/chat/"
    profile_path = str(PROJECT_ROOT / account.get("profile_dir", ""))
    os.makedirs(profile_path, exist_ok=True)
    chrome_path = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    subprocess.Popen([
        chrome_path,
        f"--user-data-dir={profile_path}",
        "--password-store=basic",
        "--use-mock-keychain",
        target_url,
    ])
    return ResponseModel(message=f"已在 Chrome 打开豆包页面（账号 {account['name']}）")


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
    project = await db.projects.find_one({"_id": ObjectId(project_id)})
    project_name = (project.get("name") or project.get("title") or "未命名")[:20] if project else "未命名"
    query = {"project_id": project_id, "video_path": {"$ne": None}}
    if video_set_id:
        query["video_set_id"] = video_set_id
    shots = await db.shots.find(query).sort("shot_no", 1).to_list(None)

    static_dir = P(__file__).parent.parent.parent / "static"
    clips = []
    for s in shots:
        vp = s.get("video_path")
        if not vp:
            continue
        fpath = static_dir / vp
        if not fpath.exists():
            continue
        clips.append((s["shot_no"], str(fpath.resolve())))

    if not clips:
        return {"ok": False, "msg": "没有已生成的视频"}

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
    template_dir = P(__file__).parent.parent / ".jianying_template"
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
    DUR = tmpl_seg["target_timerange"]["duration"]

    new_videos, new_segments, new_speeds, new_abs = [], [], [], []
    cur = 0
    for shot_no, path in clips:
        vid = str(uuid.uuid4()).upper()
        sid = str(uuid.uuid4()).upper()
        aid = str(uuid.uuid4()).upper()
        v = json.loads(json.dumps(tmpl_video))
        v["id"] = vid
        v["path"] = path
        v["material_name"] = P(path).name
        v["duration"] = DUR
        new_videos.append(v)
        new_speeds.append({"curve_speed": None, "id": sid, "mode": 0, "speed": 1.0, "type": "speed"})
        new_abs.append({"id": aid, "intensity": 0.0, "type": "audio_balance"})
        s = json.loads(json.dumps(tmpl_seg))
        s["id"] = str(uuid.uuid4()).upper()
        s["material_id"] = vid
        s["source_timerange"] = {"duration": DUR, "start": 0}
        s["target_timerange"] = {"duration": DUR, "start": cur}
        s["extra_material_refs"] = [sid, aid]
        new_segments.append(s)
        cur += DUR

    d["materials"]["videos"] = new_videos
    d["materials"]["speeds"] = new_speeds
    d["materials"]["audio_balances"] = new_abs
    d["tracks"][0]["segments"] = new_segments
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

    # 打开剪映
    subprocess.Popen(["open", "-a", "VideoFusion-macOS"])

    return {"ok": True, "msg": f"已导出{len(clips)}个视频到剪映草稿「{draft_name}」", "draft": draft_name}
