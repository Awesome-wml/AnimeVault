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


async def _migrate_legacy_project(db, project_id: str, user: dict) -> list:
    """老作品（小说存在项目上、没有集）：建「第1集」，把项目级小说搬进去，未分组的分镜和剧本归入这一集。
    只在项目确有项目级小说正文时执行，搬完清掉项目级小说，之后用户删光集也不会反复补建。"""
    if not ObjectId.is_valid(project_id):
        return []
    user_id = str(user["_id"])
    project = await db.projects.find_one({"_id": ObjectId(project_id), "user_id": user_id})
    novel = (project or {}).get("novel_content") or ""
    if not novel.strip():
        return []
    r = await db.video_sets.insert_one({
        "project_id": project_id, "name": "第1集", "order": 0,
        "novel_content": novel, "create_time": datetime.now().isoformat(),
    })
    sid = str(r.inserted_id)
    for coll in ("shots", "scripts"):
        await db[coll].update_many(
            {"project_id": project_id, "user_id": user_id, "video_set_id": None},
            {"$set": {"video_set_id": sid}},
        )
    await db.projects.update_one({"_id": ObjectId(project_id)}, {"$unset": {"novel_content": ""}})
    return await db.video_sets.find({"project_id": project_id}).sort("order", 1).to_list(None)


@router.get("/list")
async def list_sets(project_id: str, user: dict = Depends(get_current_user)):
    """列出项目下所有视频集（含每集自己的小说正文）。"""
    db = get_db()
    sets = await db.video_sets.find({"project_id": project_id}).sort("order", 1).to_list(None)
    if not sets:
        sets = await _migrate_legacy_project(db, project_id, user)
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
            "novel_content": s.get("novel_content") or "",
            "create_time": s.get("create_time", "")
        })
    return result


async def resolve_set(db, project_id: str, set_id: str, user_id: str):
    """按 project_id 定位集数；set_id 为空时取第一集。校验集属于该项目，返回集文档（无则 None）。"""
    if set_id and ObjectId.is_valid(set_id):
        return await db.video_sets.find_one({"_id": ObjectId(set_id), "project_id": project_id})
    return await db.video_sets.find_one({"project_id": project_id}, sort=[("order", 1)])


@router.post("/create")
async def create_set(body: VideoSetCreate, user: dict = Depends(get_current_user)):
    """创建新视频集（空小说、空剧本，不复制上一集内容）。"""
    db = get_db()
    # 查当前最大order
    last = await db.video_sets.find({"project_id": body.project_id}).sort("order", -1).limit(1).to_list(None)
    order = (last[0]["order"] + 1) if last else 0

    doc = {
        "project_id": body.project_id,
        "name": body.name,
        "order": order,
        "novel_content": "",
        "create_time": datetime.now().isoformat()
    }
    r = await db.video_sets.insert_one(doc)
    if order == 0:
        # 第一集：把建集前拆出的未分组分镜归入这一集，镜头数、导出、删除才和分镜页看到的一致
        await db.shots.update_many(
            {"project_id": body.project_id, "user_id": str(user["_id"]), "video_set_id": None},
            {"$set": {"video_set_id": str(r.inserted_id)}}
        )
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
    """删除视频集（同时删除下面的分镜和本集剧本）。"""
    db = get_db()
    # 删除分镜
    await db.shots.delete_many({"video_set_id": set_id})
    # 删除本集剧本场次；小说随集文档一起删除
    await db.scripts.delete_many({"video_set_id": set_id})
    # 删除集
    await db.video_sets.delete_one({"_id": ObjectId(set_id)})
    return {"ok": True, "msg": "删除成功"}
