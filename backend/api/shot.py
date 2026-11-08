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
from core.shot_timing import normalize_duration
from core.shot_voice import split_mixed_voice
from core.style_library import build_style_block, build_style_art_prompt, build_genre_rhythm
from utils.file_util import FileUtil

router = APIRouter(prefix="/api/shots", tags=["分镜管理"])
logger = logging.getLogger(__name__)

GENDER_SHORT = {"male": "男", "female": "女"}


def build_asset_block(chars: list, scenes: list, props: list) -> str:
    """把项目已有资产组成「已有资产清单」，供分镜绑定时原样引用名字。"""
    if not (chars or scenes or props):
        return "（暂无已有资产，角色、场景、道具按原文命名）"
    # 同名资产（如重复提取）只列一次
    chars = list({c["name"]: c for c in chars}.values())
    scenes = list({s["name"]: s for s in scenes}.values())
    props = list({p["name"]: p for p in props}.values())
    lines = []
    if chars:
        items = []
        for c in chars:
            tags = "、".join(t for t in (GENDER_SHORT.get(c.get("gender") or ""), c.get("age_group") or "") if t)
            items.append(f"{c['name']}（{tags}）" if tags else c["name"])
        lines.append("角色：" + "，".join(items))
    if scenes:
        lines.append("场景：" + "，".join(s["name"] for s in scenes))
    if props:
        lines.append("道具：" + "，".join(p["name"] for p in props))
    return "\n".join(lines)


def _name_list(value, allowed: set) -> list:
    """规整模型返回的名字数组；有资产清单时只保留清单里的名字。"""
    if isinstance(value, str):
        value = [v.strip() for v in value.replace("、", ",").replace("，", ",").split(",")]
    if not isinstance(value, list):
        return []
    names = []
    for v in value:
        v = str(v).strip() if v is not None else ""
        if v and v not in names and (not allowed or v in allowed):
            names.append(v)
    return names



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

    # 已有资产清单：要求模型绑定角色/场景/道具时只用这些名字
    proj_filter = {"project_id": data.project_id, "user_id": str(user["_id"])}
    asset_fields = {"name": 1, "gender": 1, "age_group": 1}
    chars = [c for c in await db.characters.find(proj_filter, asset_fields).to_list(None) if c.get("name")]
    scenes = [c for c in await db.scenes.find(proj_filter, {"name": 1}).to_list(None) if c.get("name")]
    props = [c for c in await db.props.find(proj_filter, {"name": 1}).to_list(None) if c.get("name")]
    asset_block = build_asset_block(chars, scenes, props)
    char_names = {c["name"] for c in chars}
    prop_names = {p["name"] for p in props}
    logger.info(f"[分镜] 已有资产: 角色 {len(chars)}, 场景 {len(scenes)}, 道具 {len(props)}")

    tpl = resolve_prompt(data.prompt_id, "split_shots", SHOT_SPLIT_PROMPT, category=project.get("genre"))
    prompt = safe_format(
        tpl,
        novel_paragraph=data.novel_paragraph[:3000],
        style_block=style_block,
        asset_block=asset_block,
        genre_rhythm=build_genre_rhythm(project.get("genre"), style_id),
    )
    logger.info(f"[分镜] 提示词已组装: 模板 {len(tpl)} 字, 最终请求 {len(prompt)} 字, prompt_id={data.prompt_id or '默认'}")
    messages = [{"role": "user", "content": prompt}]

    try:
        logger.info("[分镜] 开始调用大模型拆分镜...")
        result = await llm.chat_json(messages)
        shots = result.get("shots", []) or []
        logger.info(f"[分镜] 模型返回 {len(shots)} 个镜头")
        # 一个镜头只配一种声音：旁白与台词混在同一 text 时拆开
        raw_count = len(shots)
        shots = split_mixed_voice(shots, char_names)
        if len(shots) != raw_count:
            logger.info(f"[分镜] 拆开旁白/台词混合镜头: {raw_count} → {len(shots)}")
        
        # 批量插入分镜：追加到已有镜头之后，镜号接着往下编（原来每次都从 1 开始，重拆后镜号重复，
        # 视频进度、文件名、剪映排序都按镜号区分，会串）
        if shots:
            set_filter = {"$in": [target_set_id, None]} if target_set_id else None
            last = await db.shots.find(
                {"project_id": data.project_id, "user_id": str(user["_id"]), "video_set_id": set_filter},
                {"shot_no": 1},
            ).sort("shot_no", -1).limit(1).to_list(1)
            base_no = int(last[0].get("shot_no") or 0) if last else 0
            shot_docs = [
                {
                    "user_id": str(user["_id"]),
                    "project_id": data.project_id,
                    "video_set_id": target_set_id or None,
                    "shot_no": base_no + idx + 1,
                    "text": shot.get("text", ""),
                    "prompt": shot.get("prompt", ""),
                    "neg_prompt": shot.get("neg_prompt", ""),
                    "duration": normalize_duration(shot.get("duration"), shot.get("text", "")),
                    "camera": shot.get("camera", ""),
                    "character_name": shot.get("character_name"),
                    "video_prompt": shot.get("video_prompt", "") or "",
                    "scene": shot.get("scene", "") or "",
                    "positions": shot.get("positions", "") or "",
                    "characters": _name_list(shot.get("characters"), char_names),
                    "props": _name_list(shot.get("props"), prop_names),
                    "img_path": None,
                    "audio_path": None
                }
                for idx, shot in enumerate(shots)
            ]
            await db.shots.insert_many(shot_docs)
            logger.info(f"[分镜] 已落库 {len(shot_docs)} 条分镜到项目 {data.project_id}")

        return ResponseModel(
            message=f"成功拆分{len(shots)}个镜头",
            data={"count": len(shots), "shots": shots}
        )

    except Exception as e:
        logger.error(f"[分镜] 拆分失败: {type(e).__name__}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"分镜拆分失败: {str(e)}")


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
            {"video_set_id": None}  # 匹配字段缺失或为 null（拆分镜时未分组会写 null）
        ]

    cursor = db.shots.find(query).sort("shot_no", 1)

    shots = await cursor.to_list(length=500)

    # 预加载角色/场景/道具
    chars = await db.characters.find({"project_id": project_id}).to_list(None)
    scenes = await db.scenes.find({"project_id": project_id}).to_list(None)
    props = await db.props.find({"project_id": project_id}).to_list(None)

    result = []
    for s in shots:
        # 计算关联资产
        text = (s.get("text", "") or "") + " " + (s.get("prompt", "") or "") + " " + (s.get("video_prompt", "") or "")
        assets = []
        if s.get("img_path"):
            assets.append({"type": "分镜参考", "name": "画面", "img": s["img_path"]})
        for ch in chars:
            if ch.get("name") in text and ch.get("image_path"):
                assets.append({"type": "角色", "name": ch["name"], "img": ch["image_path"]})
        for sc in scenes:
            if sc.get("name") in text and sc.get("image_path"):
                assets.append({"type": "场景", "name": sc["name"], "img": sc["image_path"]})
        for pr in props:
            if pr.get("name") in text:
                img = pr.get("image_path") or pr.get("img_path")
                if img:
                    assets.append({"type": "道具", "name": pr["name"], "img": img})

        info = ShotInfo(
            id=str(s["_id"]),
            project_id=s["project_id"],
            shot_no=s["shot_no"],
            text=s["text"],
            prompt=s.get("prompt"),
            neg_prompt=s.get("neg_prompt"),
            camera=s.get("camera"),
            duration=s.get("duration"),
            video_prompt=s.get("video_prompt"),
            scene=s.get("scene"),
            positions=s.get("positions"),
            characters=s.get("characters"),
            props=s.get("props"),
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
    for field in ("camera", "duration", "scene", "positions", "characters", "props"):
        value = getattr(data, field)
        if value is not None:
            update_data[field] = value
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
