"""项目管理API"""
from fastapi import APIRouter, HTTPException, Depends
from datetime import datetime
from bson import ObjectId
from typing import List

from core.prompt_tpl import SCRIPT_PERSON_RULES
from models.schema import ProjectCreate, ProjectUpdate, ProjectInfo, ResponseModel
from db.mongo_client import get_db
from api.auth import get_current_user
from core.video_models import DEFAULT_VIDEO_MODEL_KEY, is_valid_model_key

router = APIRouter(prefix="/api/projects", tags=["项目管理"])


@router.post("")
async def create_project(data: ProjectCreate, user: dict = Depends(get_current_user)):
    """创建项目"""
    db = get_db()
    
    project_doc = {
        "user_id": str(user["_id"]),
        "name": data.name,
        "novel_content": None,
        "genre": data.genre,
        "medium": data.medium,
        "style": data.style,
        "create_time": datetime.utcnow()
    }
    
    result = await db.projects.insert_one(project_doc)
    # 小说/剧本按集归属：项目一创建就自动建第一集，作为默认写入集。
    await db.video_sets.insert_one({
        "project_id": str(result.inserted_id),
        "name": "第1集",
        "order": 0,
        "novel_content": "",
        "create_time": datetime.utcnow()
    })

    return ResponseModel(
        message="项目创建成功",
        data={"id": str(result.inserted_id)}
    )


@router.get("", response_model=List[ProjectInfo])
async def list_projects(user: dict = Depends(get_current_user)):
    """获取项目列表"""
    db = get_db()
    
    cursor = db.projects.find({"user_id": str(user["_id"])}).sort("create_time", -1)
    projects = await cursor.to_list(length=100)
    
    return [
        ProjectInfo(
            id=str(p["_id"]),
            user_id=p["user_id"],
            name=p["name"],
            novel_content=p.get("novel_content"),
            genre=p.get("genre"),
            medium=p.get("medium"),
            style=p.get("style"),
            video_model=p.get("video_model") or DEFAULT_VIDEO_MODEL_KEY,
            script_person=p.get("script_person"),
            script_target_seconds=p.get("script_target_seconds"),
            create_time=p["create_time"]
        )
        for p in projects
    ]


@router.get("/{project_id}", response_model=ProjectInfo)
async def get_project(project_id: str, user: dict = Depends(get_current_user)):
    """获取项目详情"""
    db = get_db()
    
    try:
        project = await db.projects.find_one({
            "_id": ObjectId(project_id),
            "user_id": str(user["_id"])
        })
    except Exception:
        raise HTTPException(status_code=400, detail="无效的项目ID")
    
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    
    return ProjectInfo(
        id=str(project["_id"]),
        user_id=project["user_id"],
        name=project["name"],
        novel_content=project.get("novel_content"),
        genre=project.get("genre"),
        medium=project.get("medium"),
        style=project.get("style"),
        video_model=project.get("video_model") or DEFAULT_VIDEO_MODEL_KEY,
        script_person=project.get("script_person"),
        script_target_seconds=project.get("script_target_seconds"),
        create_time=project["create_time"]
    )


@router.put("/{project_id}")
async def update_project(
    project_id: str,
    data: ProjectUpdate,
    user: dict = Depends(get_current_user)
):
    """更新项目"""
    db = get_db()
    
    try:
        obj_id = ObjectId(project_id)
    except Exception:
        raise HTTPException(status_code=400, detail="无效的项目ID")
    
    # 检查权限
    project = await db.projects.find_one({
        "_id": obj_id,
        "user_id": str(user["_id"])
    })
    
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    
    # 构建更新数据
    update_data = {}
    if data.name is not None:
        update_data["name"] = data.name
    if data.novel_content is not None:
        update_data["novel_content"] = data.novel_content
    if data.genre is not None:
        update_data["genre"] = data.genre
    if data.medium is not None:
        update_data["medium"] = data.medium
    if data.style is not None:
        update_data["style"] = data.style
    if data.video_model is not None:
        if not is_valid_model_key(data.video_model):
            raise HTTPException(status_code=400, detail="未知的视频模型")
        update_data["video_model"] = data.video_model
    if data.script_person is not None:
        if data.script_person not in SCRIPT_PERSON_RULES:
            raise HTTPException(status_code=400, detail="未知的叙事人称")
        update_data["script_person"] = data.script_person
    if data.script_target_seconds is not None:
        update_data["script_target_seconds"] = data.script_target_seconds or None
    
    if update_data:
        await db.projects.update_one(
            {"_id": obj_id},
            {"$set": update_data}
        )
    
    return ResponseModel(message="项目更新成功")


@router.delete("/{project_id}")
async def delete_project(project_id: str, user: dict = Depends(get_current_user)):
    """删除项目"""
    db = get_db()
    
    try:
        obj_id = ObjectId(project_id)
    except Exception:
        raise HTTPException(status_code=400, detail="无效的项目ID")
    
    # 检查权限
    project = await db.projects.find_one({
        "_id": obj_id,
        "user_id": str(user["_id"])
    })
    
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    
    # 删除项目
    await db.projects.delete_one({"_id": obj_id})
    
    # 删除关联的角色
    await db.characters.delete_many({"project_id": project_id})
    
    # 删除关联的分镜
    await db.shots.delete_many({"project_id": project_id})

    # 删除关联的场景、道具、剧集、剧本（此前会残留成孤儿数据）
    await db.scenes.delete_many({"project_id": project_id})
    await db.props.delete_many({"project_id": project_id})
    await db.scripts.delete_many({"project_id": project_id})
    await db.video_sets.delete_many({"project_id": project_id})
    
    return ResponseModel(message="项目删除成功")
