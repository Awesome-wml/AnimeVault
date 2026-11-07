"""场景管理API"""
from fastapi import APIRouter, HTTPException, Depends
from bson import ObjectId
from typing import List

from models.schema import SceneCreate, SceneUpdate, SceneInfo, SceneExtract, ResponseModel
from db.mongo_client import get_db
from api.auth import get_current_user
from core.prompt_tpl import SCENE_EXTRACT_PROMPT
from core.llm_factory import build_provider, resolve_prompt, safe_format
from core.style_library import build_style_block
from utils.file_util import FileUtil

router = APIRouter(prefix="/api/scenes", tags=["场景管理"])


@router.post("/extract")
async def extract_scenes(data: SceneExtract, user: dict = Depends(get_current_user)):
    """AI提取场景"""
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

    # 构建提示词（注入风格；可按提示词ID覆盖）
    style_block = build_style_block(data.style) if data.style else ""
    tpl = resolve_prompt(data.prompt_id, "scene_extract", SCENE_EXTRACT_PROMPT, category=project.get("genre"))
    prompt = safe_format(
        tpl,
        novel_text=data.novel_text[:5000],
        style_block=style_block
    )
    messages = [{"role": "user", "content": prompt}]

    try:
        result = await llm.chat_json(messages)
        scenes = result.get("scenes", [])

        # 批量插入场景
        if scenes:
            scene_docs = [
                {
                    "user_id": str(user["_id"]),
                    "project_id": data.project_id,
                    "name": s["name"],
                    "scene_type": s.get("scene_type", ""),
                    "description": s.get("description", ""),
                    "image_path": None
                }
                for s in scenes
            ]
            await db.scenes.insert_many(scene_docs)

        return ResponseModel(
            message=f"成功提取{len(scenes)}个场景",
            data={"count": len(scenes), "scenes": scenes}
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"场景提取失败: {str(e)}")


@router.post("")
async def create_scene(data: SceneCreate, user: dict = Depends(get_current_user)):
    """创建场景"""
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

    scene_doc = {
        "user_id": str(user["_id"]),
        "project_id": data.project_id,
        "name": data.name,
        "scene_type": data.scene_type,
        "description": data.description,
        "image_path": data.image_path
    }

    result = await db.scenes.insert_one(scene_doc)

    return ResponseModel(
        message="场景创建成功",
        data={"id": str(result.inserted_id)}
    )


@router.get("", response_model=List[SceneInfo])
async def list_scenes(project_id: str, user: dict = Depends(get_current_user)):
    """获取场景列表"""
    db = get_db()

    cursor = db.scenes.find({
        "user_id": str(user["_id"]),
        "project_id": project_id
    })
    scenes = await cursor.to_list(length=100)

    return [
        SceneInfo(
            id=str(s["_id"]),
            user_id=s["user_id"],
            project_id=s["project_id"],
            name=s["name"],
            scene_type=s.get("scene_type"),
            description=s.get("description"),
            image_path=s.get("image_path")
        )
        for s in scenes
    ]


@router.put("/{scene_id}")
async def update_scene(
    scene_id: str,
    data: SceneUpdate,
    user: dict = Depends(get_current_user)
):
    """更新场景"""
    db = get_db()

    try:
        obj_id = ObjectId(scene_id)
    except Exception:
        raise HTTPException(status_code=400, detail="无效的场景ID")

    # 检查权限
    scene = await db.scenes.find_one({
        "_id": obj_id,
        "user_id": str(user["_id"])
    })

    if not scene:
        raise HTTPException(status_code=404, detail="场景不存在")

    # 构建更新数据
    update_data = {}
    if data.name is not None:
        update_data["name"] = data.name
    if data.scene_type is not None:
        update_data["scene_type"] = data.scene_type
    if data.description is not None:
        update_data["description"] = data.description
    if data.image_path is not None:
        update_data["image_path"] = data.image_path

    if update_data:
        await db.scenes.update_one(
            {"_id": obj_id},
            {"$set": update_data}
        )

    return ResponseModel(message="场景更新成功")


@router.delete("/{scene_id}")
async def delete_scene(scene_id: str, user: dict = Depends(get_current_user)):
    """删除场景"""
    db = get_db()

    try:
        obj_id = ObjectId(scene_id)
    except Exception:
        raise HTTPException(status_code=400, detail="无效的场景ID")

    # 检查权限
    scene = await db.scenes.find_one({
        "_id": obj_id,
        "user_id": str(user["_id"])
    })

    if not scene:
        raise HTTPException(status_code=404, detail="场景不存在")

    # 删除关联图片
    if scene.get("image_path"):
        FileUtil.delete_file(scene["image_path"])

    await db.scenes.delete_one({"_id": obj_id})

    return ResponseModel(message="场景删除成功")
