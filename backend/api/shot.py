"""分镜管理API"""
from fastapi import APIRouter, HTTPException, Depends
from bson import ObjectId
from typing import List

from models.schema import ShotCreate, ShotUpdate, ShotInfo, ShotSplit, ResponseModel
from db.mongo_client import get_db
from api.auth import get_current_user
from core.prompt_tpl import SHOT_SPLIT_PROMPT
from core.llm_factory import build_provider, resolve_prompt, safe_format
from core.style_library import build_style_block, build_style_art_prompt
from utils.file_util import FileUtil

router = APIRouter(prefix="/api/shots", tags=["分镜管理"])


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

    # 获取LLM提供者（可按模型预设覆盖）
    llm = build_provider(user, data.model_id, data.model)

    # 读取项目风格，注入到分镜拆分提示词（可按提示词ID覆盖）
    style_id = project.get("style")
    style_block = build_style_block(style_id) if style_id else ""
    tpl = resolve_prompt(data.prompt_id, "split_shots", SHOT_SPLIT_PROMPT, category=project.get("genre"))
    prompt = safe_format(
        tpl,
        novel_paragraph=data.novel_paragraph[:3000],
        style_block=style_block
    )
    messages = [{"role": "user", "content": prompt}]
    
    try:
        result = await llm.chat_json(messages)
        shots = result.get("shots", [])
        
        # 批量插入分镜
        if shots:
            shot_docs = [
                {
                    "user_id": str(user["_id"]),
                    "project_id": data.project_id,
                    "shot_no": shot.get("shot_no", idx + 1),
                    "text": shot.get("text", ""),
                    "prompt": shot.get("prompt", ""),
                    "neg_prompt": shot.get("neg_prompt", ""),
                    "duration": shot.get("duration", 15.0),
                    "camera": shot.get("camera", ""),
                    "character_name": shot.get("character_name"),
                    "img_path": None,
                    "audio_path": None
                }
                for idx, shot in enumerate(shots)
            ]
            await db.shots.insert_many(shot_docs)
        
        return ResponseModel(
            message=f"成功拆分{len(shots)}个镜头",
            data={"count": len(shots), "shots": shots}
        )
        
    except Exception as e:
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
        query["video_set_id"] = video_set_id

    cursor = db.shots.find(query).sort("shot_no", 1)

    shots = await cursor.to_list(length=500)

    # 预加载角色/场景/道具
    chars = await db.characters.find({"project_id": project_id}).to_list(None)
    scenes = await db.scenes.find({"project_id": project_id}).to_list(None)
    props = await db.props.find({"project_id": project_id}).to_list(None)

    result = []
    for s in shots:
        # 计算关联资产
        text = (s.get("text", "") or "") + " " + (s.get("video_prompt", "") or "")
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
