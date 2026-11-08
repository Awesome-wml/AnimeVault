"""分镜管理API"""
import logging
from fastapi import APIRouter, HTTPException, Depends
from bson import ObjectId
from typing import List

from models.schema import ShotCreate, ShotUpdate, ShotInfo, ShotSplit, ResponseModel
from db.mongo_client import get_db
from api.auth import get_current_user
from core.prompt_tpl import SHOT_SPLIT_PROMPT
from core.llm_factory import build_provider, resolve_prompt, safe_format
from core.style_library import build_style_block, build_style_art_prompt
from core.asset_binding import collect_bindings, build_video_prompt
from core.script_text import scripts_to_text
from core.sse import run_with_sse
from utils.file_util import FileUtil

router = APIRouter(prefix="/api/shots", tags=["分镜管理"])
logger = logging.getLogger(__name__)


@router.post("/split")
async def split_shots(data: ShotSplit, user: dict = Depends(get_current_user)):
    """AI拆分分镜"""
    db = get_db()

    # 检查项目权限
    try:
        project = await db.projects.find_one({
            "_id": ObjectId(data.project_id),
            "user_id": str(user["_id"])
        })
    except Exception:
        raise HTTPException(status_code=400, detail="无效的项目ID")

    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    logger.info(f"[分镜] 收到拆分镜请求: project_id={data.project_id}, 小说段落 {len(data.novel_paragraph or '')} 字")

    # 解析要绑定的视频分组：优先请求传入，否则取项目默认分组
    target_set_id = (data.video_set_id or "").strip()
    if not target_set_id:
        vset = await db.video_sets.find_one({"project_id": data.project_id})
        if vset:
            target_set_id = str(vset["_id"])
    logger.info(f"[分镜] 绑定视频分组: {target_set_id or '未分组'}")

    # 获取LLM提供者（可按模型预设覆盖）
    llm = build_provider(user, data.model_id, data.model)
    logger.info(f"[分镜] 使用模型: model_id={data.model_id or '全局默认'}, model={data.model or '默认'}")

    # 读取项目风格，注入到分镜拆分提示词（可按提示词ID覆盖）
    style_id = project.get("style")
    style_block = build_style_block(style_id) if style_id else ""

    # 优先基于剧本场次拆分；无剧本时兜底小说段落
    scripts = await db.scripts.find({"project_id": data.project_id}).to_list(None)
    source_text = scripts_to_text(scripts) if scripts else data.novel_paragraph
    logger.info(f"[分镜] 拆分依据: {'剧本 ' + str(len(scripts)) + ' 场' if scripts else '小说段落'}")

    tpl = resolve_prompt(data.prompt_id, "split_shots", SHOT_SPLIT_PROMPT, category=project.get("genre"))
    prompt = safe_format(
        tpl,
        novel_paragraph=source_text[:3000],
        style_block=style_block
    )
    logger.info(f"[分镜] 提示词已组装: 模板 {len(tpl)} 字, 最终请求 {len(prompt)} 字, prompt_id={data.prompt_id or '默认'}")
    messages = [{"role": "user", "content": prompt}]

    async def build_task(report):
        logger.info("[分镜] 开始调用大模型拆分镜...")
        result = await llm.chat_json(messages, on_progress=report)
        shots = result.get("shots", [])
        logger.info(f"[分镜] 模型返回 {len(shots)} 个镜头")

        # 批量插入分镜（先算好资产绑定与豆包提示词）
        chars = await db.characters.find({"project_id": data.project_id}).to_list(None)
        scenes = await db.scenes.find({"project_id": data.project_id}).to_list(None)
        props = await db.props.find({"project_id": data.project_id}).to_list(None)
        # 场次编号 → 地点，供场景归属匹配
        location_by_scene = {
            sc.get("scene_no"): (sc.get("location") or "") for sc in scripts
        }

        shot_docs = []
        for idx, shot in enumerate(shots):
            doc = {
                "user_id": str(user["_id"]),
                "project_id": data.project_id,
                "video_set_id": target_set_id or None,
                "shot_no": shot.get("shot_no", idx + 1),
                "scene_no": shot.get("scene_no"),
                "text": shot.get("text", ""),
                "prompt": shot.get("prompt", ""),
                "neg_prompt": shot.get("neg_prompt", ""),
                "duration": shot.get("duration", 15.0),
                "camera": shot.get("camera", ""),
                "character_name": shot.get("character_name"),
                "img_path": None,
                "audio_path": None
            }
            bindings = collect_bindings(
                doc, chars, scenes, props,
                scene_location=location_by_scene.get(doc.get("scene_no"), ""),
            )
            doc["bindings"] = bindings
            doc["video_prompt"] = build_video_prompt(doc, bindings)
            shot_docs.append(doc)

        await db.shots.insert_many(shot_docs)
        logger.info(f"[分镜] 已落库 {len(shot_docs)} 条分镜到项目 {data.project_id}")

        return f"成功拆分{len(shots)}个镜头", {"count": len(shots), "shots": shots}

    return await run_with_sse(build_task)


@router.post("")
async def create_shot(data: ShotCreate, user: dict = Depends(get_current_user)):
    """创建分镜"""
    db = get_db()
    
    # 检查项目权限
    try:
        project = await db.projects.find_one({
            "_id": ObjectId(data.project_id),
            "user_id": str(user["_id"])
        })
    except Exception:
        raise HTTPException(status_code=400, detail="无效的项目ID")
    
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    
    shot_doc = {
        "user_id": str(user["_id"]),
        "project_id": data.project_id,
        "shot_no": data.shot_no,
        "text": data.text,
        "prompt": data.prompt,
        "neg_prompt": data.neg_prompt,
        "duration": data.duration,
        "character_name": data.character_name,
        "img_path": None,
        "audio_path": None
    }
    
    result = await db.shots.insert_one(shot_doc)
    
    return ResponseModel(
        message="分镜创建成功",
        data={"id": str(result.inserted_id)}
    )


@router.get("")
async def list_shots(project_id: str, video_set_id: str = "", user: dict = Depends(get_current_user)):
    """获取分镜列表"""
    db = get_db()

    query = {
        "user_id": str(user["_id"]),
        "project_id": project_id
    }
    if video_set_id:
        # 同时包含指定分组内、以及尚未绑定分组的分镜，避免未分组分镜被过滤掉
        query["$or"] = [
            {"video_set_id": video_set_id},
            {"video_set_id": {"$exists": False}}
        ]

    cursor = db.shots.find(query).sort("shot_no", 1)

    shots = await cursor.to_list(length=500)

    # 预加载角色/场景/道具
    chars = await db.characters.find({"project_id": project_id}).to_list(None)
    scenes = await db.scenes.find({"project_id": project_id}).to_list(None)
    props = await db.props.find({"project_id": project_id}).to_list(None)
    scripts = await db.scripts.find({"project_id": project_id}).to_list(None)
    location_by_scene = {
        sc.get("scene_no"): (sc.get("location") or "") for sc in scripts
    }

    result = []
    for s in shots:
        # 计算资产-分镜绑定（角色 → 场景 → 道具，去重）
        bindings = collect_bindings(
            s, chars, scenes, props,
            scene_location=location_by_scene.get(s.get("scene_no"), ""),
        )
        assets = []
        if s.get("img_path"):
            assets.append({"type": "分镜参考", "role": "frame", "label": "画面",
                           "asset_id": None, "name": "画面", "img": s["img_path"]})
        for b in bindings:
            assets.append({
                "type": b["asset_type"],
                "role": b["role"],
                "label": b["label"],
                "asset_id": b["asset_id"],
                "name": b["name"],
                "img": b["img"],
            })

        info = ShotInfo(
            id=str(s["_id"]),
            project_id=s["project_id"],
            shot_no=s["shot_no"],
            scene_no=s.get("scene_no"),
            text=s["text"],
            prompt=s.get("prompt"),
            neg_prompt=s.get("neg_prompt"),
            camera=s.get("camera"),
            duration=s.get("duration"),
            video_prompt=s.get("video_prompt"),
            video_path=s.get("video_path"),
            img_path=s.get("img_path"),
            character_name=s.get("character_name")
        )
        result.append({**info.dict(), "assets": assets})

    return result


@router.put("/{shot_id}")
async def update_shot(
    shot_id: str,
    data: ShotUpdate,
    user: dict = Depends(get_current_user)
):
    """更新分镜"""
    db = get_db()
    
    try:
        obj_id = ObjectId(shot_id)
    except Exception:
        raise HTTPException(status_code=400, detail="无效的分镜ID")
    
    # 检查权限
    shot = await db.shots.find_one({
        "_id": obj_id,
        "user_id": str(user["_id"])
    })
    
    if not shot:
        raise HTTPException(status_code=404, detail="分镜不存在")
    
    # 构建更新数据
    update_data = {}
    if data.shot_no is not None:
        update_data["shot_no"] = data.shot_no
    if data.text is not None:
        update_data["text"] = data.text
    if data.prompt is not None:
        update_data["prompt"] = data.prompt
    if data.neg_prompt is not None:
        update_data["neg_prompt"] = data.neg_prompt
    if data.video_prompt is not None:
        update_data["video_prompt"] = data.video_prompt
    if data.character_name is not None:
        update_data["character_name"] = data.character_name
    if data.img_path is not None:
        update_data["img_path"] = data.img_path
    
    if update_data:
        await db.shots.update_one(
            {"_id": obj_id},
            {"$set": update_data}
        )
    
    return ResponseModel(message="分镜更新成功")


@router.delete("/{shot_id}")
async def delete_shot(shot_id: str, user: dict = Depends(get_current_user)):
    """删除分镜"""
    db = get_db()
    
    try:
        obj_id = ObjectId(shot_id)
    except Exception:
        raise HTTPException(status_code=400, detail="无效的分镜ID")
    
    # 检查权限
    shot = await db.shots.find_one({
        "_id": obj_id,
        "user_id": str(user["_id"])
    })
    
    if not shot:
        raise HTTPException(status_code=404, detail="分镜不存在")
    
    # 删除关联的图片和音频文件
    if shot.get("img_path"):
        FileUtil.delete_file(shot["img_path"])
    if shot.get("audio_path"):
        FileUtil.delete_file(shot["audio_path"])
    
    await db.shots.delete_one({"_id": obj_id})
    
    return ResponseModel(message="分镜删除成功")
