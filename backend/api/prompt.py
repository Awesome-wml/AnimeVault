"""提示词管理 API

内置提示词由 core/builtin_prompts.sync_builtin_prompts 在启动时同步进库（main.py lifespan），
这里只做增删改查、恢复内置、复制为自定义。取值顺序见 core/prompt_store.get_prompt。
"""
from datetime import datetime

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException

from api.auth import get_current_user
from core.builtin_prompts import GENERAL_CATEGORY, builtin_for, builtin_state, content_hash
from core.style_library import GENRES
from db.sync_client import get_sync_db

router = APIRouter(prefix="/api/prompts", tags=["prompts"], dependencies=[Depends(get_current_user)])

db = get_sync_db()

# 题材流派分类：通用兜底 + 现有风格库题材 + 韩剧；与项目 genre 取值对齐
_CATEGORY_IDS = [GENERAL_CATEGORY] + [g["genre"] for g in GENRES] + ["韩剧"]
CATEGORIES = list(dict.fromkeys(_CATEGORY_IDS))

# 列表不回传的内部字段（latest_builtin 走 restore 接口）
_HIDDEN = ("builtin_hash", "latest_builtin")


def _oid(pid: str) -> ObjectId:
    try:
        return ObjectId(pid)
    except Exception:
        raise HTTPException(status_code=400, detail="无效的提示词 ID")


def _get(pid: str) -> dict:
    p = db.prompts.find_one({"_id": _oid(pid)})
    if not p:
        raise HTTPException(status_code=404, detail="提示词不存在")
    return p


def _norm_category(body: dict) -> dict:
    body["category"] = (body.get("category") or GENERAL_CATEGORY).strip() or GENERAL_CATEGORY
    return body


def _clear_default(type: str, category: str):
    """同 type + 同题材只能有一条用户默认（内置记录不参与）"""
    db.prompts.update_many({"type": type, "category": category, "is_builtin": {"$ne": True}},
                           {"$set": {"is_default": False}})


def _public(p: dict) -> dict:
    p["_id"] = str(p["_id"])
    p["category"] = p.get("category") or GENERAL_CATEGORY
    p["is_builtin"] = bool(p.get("is_builtin"))
    p["is_default"] = bool(p.get("is_default"))
    p["has_update"] = bool(p.get("has_update")) if p["is_builtin"] else False
    for k in _HIDDEN:
        p.pop(k, None)
    return p


@router.get("")
def list_prompts(type: str = "", category: str = ""):
    q = {}
    if type:
        q["type"] = type
    if category:
        q["category"] = category
    proms = [_public(p) for p in db.prompts.find(q).sort("created_at", -1)]
    return {"data": proms, "categories": CATEGORIES}


@router.post("")
def create_prompt(body: dict):
    body = _norm_category(body)
    body.pop("_id", None)
    for k in ("is_builtin", "has_update", *_HIDDEN):
        body.pop(k, None)
    body["is_builtin"] = False
    body["created_at"] = datetime.now()
    if body.get("is_default"):
        _clear_default(body.get("type"), body["category"])
    r = db.prompts.insert_one(body)
    return {"id": str(r.inserted_id)}


@router.put("/{pid}")
def update_prompt(pid: str, body: dict):
    cur = _get(pid)
    body.pop("_id", None)
    if cur.get("is_builtin"):
        # 内置只允许改正文；改完按 hash 判断是否与代码一致 / 是否落后于代码
        if "content" not in body:
            raise HTTPException(status_code=400, detail="内置提示词只能修改内容")
        content = str(body.get("content") or "")
        if not content.strip():
            raise HTTPException(status_code=400, detail="内容不能为空")
        state = builtin_state(cur["type"], content, cur.get("builtin_hash") or "", from_code=False)
        fields = {**state["set"], "content": content, "updated_at": datetime.now()}
        update = {"$set": fields}
        if state["unset"]:
            update["$unset"] = {k: "" for k in state["unset"]}
        db.prompts.update_one({"_id": cur["_id"]}, update)
        return {"ok": True, "has_update": bool(fields.get("has_update"))}

    for k in ("is_builtin", "has_update", *_HIDDEN):
        body.pop(k, None)
    body = _norm_category({"category": cur.get("category"), **body})
    if body.get("is_default"):
        _clear_default(body.get("type") or cur.get("type"), body["category"])
    db.prompts.update_one({"_id": cur["_id"]}, {"$set": body})
    return {"ok": True}


@router.post("/{pid}/restore")
def restore_prompt(pid: str):
    """内置提示词恢复成代码里的最新版本"""
    cur = _get(pid)
    bp = builtin_for(cur.get("type")) if cur.get("is_builtin") else None
    if not bp:
        raise HTTPException(status_code=400, detail="只有内置提示词可以恢复")
    db.prompts.update_one({"_id": cur["_id"]}, {
        "$set": {"content": bp["content"], "builtin_hash": content_hash(bp["content"]),
                 "has_update": False, "updated_at": datetime.now()},
        "$unset": {"latest_builtin": ""},
    })
    return {"ok": True, "content": bp["content"]}


@router.post("/{pid}/duplicate")
def duplicate_prompt(pid: str, body: dict = None):
    """复制为自定义提示词（内置或自定义都可以复制）；body 可带 name / category"""
    cur = _get(pid)
    body = body or {}
    name = (body.get("name") or "").strip() or f"{cur.get('name', '')}（副本）"
    category = (body.get("category") or cur.get("category") or GENERAL_CATEGORY).strip() or GENERAL_CATEGORY
    doc = {
        "name": name, "type": cur.get("type"), "category": category, "version": "v1.0",
        "content": cur.get("content") or "", "is_default": False, "is_builtin": False,
        "created_at": datetime.now(),
    }
    r = db.prompts.insert_one(doc)
    return {"id": str(r.inserted_id)}


@router.delete("/{pid}")
def delete_prompt(pid: str):
    cur = _get(pid)
    if cur.get("is_builtin"):
        raise HTTPException(status_code=400, detail="内置提示词不能删除，可以修改内容或恢复内置")
    db.prompts.delete_one({"_id": cur["_id"]})
    return {"ok": True}
