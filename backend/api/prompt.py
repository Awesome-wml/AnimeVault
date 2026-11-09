from fastapi import APIRouter, HTTPException
from db.sync_client import get_sync_db
from datetime import datetime
from bson import ObjectId

from core.style_library import STYLE_LIBRARY

router = APIRouter(prefix="/api/prompts", tags=["prompts"])

db = get_sync_db()

# 题材流派分类：通用兜底 + 现有风格库题材 + 韩剧；与项目 genre 取值对齐
GENERAL_CATEGORY = "通用"
_CATEGORY_IDS = [GENERAL_CATEGORY] + [s["genre"] for s in STYLE_LIBRARY] + ["韩剧"]
CATEGORIES = list(dict.fromkeys(_CATEGORY_IDS))

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
            p["category"] = GENERAL_CATEGORY
            p["created_at"] = datetime.now()
            db.prompts.insert_one(p)


def _norm_category(body: dict) -> dict:
    body["category"] = (body.get("category") or GENERAL_CATEGORY).strip() or GENERAL_CATEGORY
    return body


@router.get("")
def list_prompts(type: str = "", category: str = ""):
    q = {}
    if type:
        q["type"] = type
    if category:
        q["category"] = category
    proms = list(db.prompts.find(q).sort("created_at", -1))
    for p in proms:
        p["_id"] = str(p["_id"])
        if not p.get("category"):
            p["category"] = GENERAL_CATEGORY
    return {"data": proms, "categories": CATEGORIES}


@router.post("")
def create_prompt(body: dict):
    body = _norm_category(body)
    body["created_at"] = datetime.now()
    if body.get("is_default"):
        db.prompts.update_many(
            {"type": body.get("type"), "category": body["category"]},
            {"$set": {"is_default": False}},
        )
    r = db.prompts.insert_one(body)
    return {"id": str(r.inserted_id)}


@router.put("/{pid}")
def update_prompt(pid: str, body: dict):
    body.pop("_id", None)
    body = _norm_category(body)
    if body.get("is_default"):
        db.prompts.update_many(
            {"type": body.get("type"), "category": body["category"]},
            {"$set": {"is_default": False}},
        )
    db.prompts.update_one({"_id": ObjectId(pid)}, {"$set": body})
    return {"ok": True}


@router.delete("/{pid}")
def delete_prompt(pid: str):
    db.prompts.delete_one({"_id": ObjectId(pid)})
    return {"ok": True}
