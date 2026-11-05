from fastapi import APIRouter, HTTPException
from pymongo import MongoClient
from datetime import datetime
from bson import ObjectId
import os

router = APIRouter(prefix="/api/prompts", tags=["prompts"])

client = MongoClient(os.environ.get("MONGO_URL", "mongodb://admin:dongai_mongo_2024@localhost:27017/"))
db = client.dongai

# 类型: novel(生成小说) / split_shots(拆分镜) / video(视频提示词)
DEFAULT_PROMPTS = [
    {
        "name": "默认视频提示词",
        "type": "video",
        "version": "v1.0",
        "content": "【硬性参数】严格成长度为15秒，16:9横屏，无水印、无平台标识、无角标、无logo。",
        "is_default": True,
        "is_builtin": True,
    },
    {
        "name": "默认拆分校词",
        "type": "split_shots",
        "version": "v1.0",
        "content": "你是一个专业的短剧分镜师。请将以下小说段落拆分为若干个分镜...",
        "is_default": True,
        "is_builtin": True,
    },
]

@router.on_event("startup")
def seed():
    """首次运行插入默认提示词"""
    for p in DEFAULT_PROMPTS:
        if not db.prompts.find_one({"type": p["type"], "is_builtin": True}):
            p["created_at"] = datetime.now()
            db.prompts.insert_one(p)

@router.get("")
def list_prompts(type: str = ""):
    q = {}
    if type:
        q["type"] = type
    proms = list(db.prompts.find(q).sort("created_at", -1))
    for p in proms:
        p["_id"] = str(p["_id"])
    return {"data": proms}

@router.post("")
def create_prompt(body: dict):
    body["created_at"] = datetime.now()
    if body.get("is_default"):
        db.prompts.update_many({"type": body.get("type")}, {"$set": {"is_default": False}})
    r = db.prompts.insert_one(body)
    return {"id": str(r.inserted_id)}

@router.put("/{pid}")
def update_prompt(pid: str, body: dict):
    if body.get("is_default"):
        db.prompts.update_many({"type": body.get("type")}, {"$set": {"is_default": False}})
    db.prompts.update_one({"_id": ObjectId(pid)}, {"$set": body})
    return {"ok": True}

@router.delete("/{pid}")
def delete_prompt(pid: str):
    db.prompts.delete_one({"_id": ObjectId(pid)})
    return {"ok": True}
