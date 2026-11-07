from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from bson import ObjectId
from db.mongo_client import get_db
from api.auth import get_current_user

router = APIRouter(prefix="/api/video-set", tags=["video-set"])


class VideoSetCreate(BaseModel):
    project_id: str
    name: str


class VideoSetRename(BaseModel):
    name: str


@router.get("/list")
async def list_sets(project_id: str, user: dict = Depends(get_current_user)):
    """列出项目下所有视频集"""
    db = get_db()
    sets = await db.video_sets.find({"project_id": project_id}).sort("order", 1).to_list(None)
    result = []
    for s in sets:
        # 统计每个集的分镜数和已生成视频数
        shot_count = await db.shots.count_documents({"video_set_id": str(s["_id"])})
        video_count = await db.shots.count_documents({"video_set_id": str(s["_id"]), "video_path": {"$ne": None}})
        result.append({
            "id": str(s["_id"]),
            "name": s["name"],
            "order": s.get("order", 0),
            "shot_count": shot_count,
            "video_count": video_count,
            "create_time": s.get("create_time", "")
        })
    return result


@router.post("/create")
async def create_set(body: VideoSetCreate, user: dict = Depends(get_current_user)):
    """创建新视频集"""
    db = get_db()
    # 查当前最大order
    last = await db.video_sets.find({"project_id": body.project_id}).sort("order", -1).limit(1).to_list(None)
    order = (last[0]["order"] + 1) if last else 0
    
    doc = {
        "project_id": body.project_id,
        "name": body.name,
        "order": order,
        "create_time": datetime.now().isoformat()
    }
    r = await db.video_sets.insert_one(doc)
    return {"ok": True, "id": str(r.inserted_id), "msg": "创建成功"}


@router.post("/rename")
async def rename_set(set_id: str, body: VideoSetRename, user: dict = Depends(get_current_user)):
    """重命名视频集"""
    db = get_db()
    await db.video_sets.update_one(
        {"_id": ObjectId(set_id)},
        {"$set": {"name": body.name}}
    )
    return {"ok": True, "msg": "重命名成功"}


@router.delete("/delete")
async def delete_set(set_id: str, user: dict = Depends(get_current_user)):
    """删除视频集（同时删除下面的分镜）"""
    db = get_db()
    # 删除分镜
    await db.shots.delete_many({"video_set_id": set_id})
    # 删除集
    await db.video_sets.delete_one({"_id": ObjectId(set_id)})
    return {"ok": True, "msg": "删除成功"}
