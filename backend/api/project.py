"""项目管理API"""
from fastapi import APIRouter, HTTPException, Depends
from datetime import datetime
from bson import ObjectId
from typing import List

from models.schema import ProjectCreate, ProjectUpdate, ProjectInfo, ResponseModel
from db.mongo_client import get_db
from api.auth import get_current_user

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
        "style": data.style,
        "create_time": datetime.utcnow()
    }
    
    result = await db.projects.insert_one(project_doc)
    
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
            style=p.get("style"),
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
        style=project.get("style"),
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
    if data.style is not None:
        update_data["style"] = data.style
    
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
    
    return ResponseModel(message="项目删除成功")
