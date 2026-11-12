"""场景管理API"""
from fastapi import APIRouter, HTTPException, Depends
from bson import ObjectId
from typing import List

from models.schema import SceneCreate, SceneUpdate, SceneInfo, SceneExtract, ResponseModel
from db.mongo_client import get_db
from api.auth import get_current_user
from core.llm_factory import build_provider
from core.prompt_registry import build_messages
from core.style_library import build_style_block
from core.scene_views import scene_doc_fields, clean_state_note, merge_views_update, public_views
from utils.file_util import FileUtil

router = APIRouter(prefix="/api/scenes", tags=["场景管理"])


def scene_doc(user_id: str, project_id: str, s: dict) -> dict:
    """模型提取的一个场景 → 入库文档（单项提取与全量提取共用；state_note / views 见 core/scene_views）。"""
    fields = scene_doc_fields(s)
    return {
        "user_id": user_id,
        "project_id": project_id,
        "name": s.get("name", ""),
        "scene_type": s.get("scene_type", ""),
        "description": s.get("description", ""),
        "state_note": fields["state_note"],
        "views": fields["views"],
        "image_path": fields["image_path"],
    }


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

    # 构建提示词：骨架来自 system.json，约束来自 constraints.json，数据运行时填入
    style_block = build_style_block(medium=data.medium, genre=data.genre, style_id=data.style)
    messages = build_messages(
        "scene_extract",
        variant=project.get("genre"),
        novel_text=data.novel_text[:5000],
        style_block=style_block,
    )

    try:
        result = await llm.chat_json(messages)
        scenes = result.get("scenes", [])

        # 批量插入场景
        if scenes:
            scene_docs = [scene_doc(str(user["_id"]), data.project_id, s)
                          for s in scenes if isinstance(s, dict) and s.get("name")]
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

    scene_doc_ = {
        "user_id": str(user["_id"]),
        "project_id": data.project_id,
        "name": data.name,
        "scene_type": data.scene_type,
        "description": data.description,
        "state_note": clean_state_note(data.state_note),
        "image_path": data.image_path,
    }
    doc_fields = scene_doc_fields({"views": data.views, "state_note": data.state_note})
    scene_doc_["views"] = doc_fields["views"]

    result = await db.scenes.insert_one(scene_doc_)

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
            image_path=s.get("image_path"),
            state_note=s.get("state_note") or "",
            views=public_views(s),
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
    if data.state_note is not None:
        update_data["state_note"] = clean_state_note(data.state_note)
    if data.views is not None:
        # 沿用原视角的图；第一视角的图与 image_path 互为镜像
        views = merge_views_update(scene, data.views)
        update_data["views"] = views
        update_data["image_path"] = views[0].get("image_path")

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
