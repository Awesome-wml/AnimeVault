"""项目管理API"""
from fastapi import APIRouter, HTTPException, Depends
from datetime import datetime
from bson import ObjectId
from typing import List

from core.prompt_tpl import SCRIPT_PERSON_RULES
from models.schema import ProjectCreate, ProjectUpdate, ProjectInfo, ResponseModel, StyleSuggest
from db.mongo_client import get_db
from api.auth import get_current_user
from core.video_models import DEFAULT_VIDEO_MODEL_KEY, is_valid_model_key

from core.style_library import FALLBACK_MEDIUM
from core.style_suggest import (STYLE_SOURCE_AI, STYLE_SOURCE_AUTO, STYLE_SOURCE_USER, apply_fields, suggest_style)

router = APIRouter(prefix="/api/projects", tags=["项目管理"])


@router.post("")
async def create_project(data: ProjectCreate, user: dict = Depends(get_current_user)):
    """创建项目"""
    db = get_db()
    
    auto = data.style_source == STYLE_SOURCE_AUTO
    project_doc = {
        "user_id": str(user["_id"]),
        "name": data.name,
        "novel_content": None,
        "genre": None if auto else data.genre,
        # 画面类型不许静默为空：没选媒介也没有旧风格时落缺省（真人实拍），全链路统一；
        # 待识别的作品也先落缺省，贴入小说后由 AI 识别覆盖（core/style_suggest.py）
        "medium": (FALLBACK_MEDIUM if auto else data.medium) or (None if data.style else FALLBACK_MEDIUM),
        "style": None if auto else data.style,
        "style_source": STYLE_SOURCE_AUTO if auto else STYLE_SOURCE_USER,
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
            style_source=p.get("style_source"),
            style_reason=p.get("style_reason"),
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
        style_source=project.get("style_source"),
        style_reason=project.get("style_reason"),
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
    if data.style_source in (STYLE_SOURCE_AUTO, STYLE_SOURCE_AI, STYLE_SOURCE_USER):
        update_data["style_source"] = data.style_source
    elif data.medium is not None or data.genre is not None:
        # 用户在风格页手动保存：以用户为准，之后不再自动识别覆盖
        update_data["style_source"] = STYLE_SOURCE_USER
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


async def _style_text(db, project: dict, project_id: str, video_set_id: str, user_id: str) -> str:
    """识别风格用的正文：本集小说 → 作品级小说 → 第一集 → 剧本台词。"""
    from api.video_set import resolve_set
    set_doc = await resolve_set(db, project_id, video_set_id, user_id)
    text = (set_doc or {}).get("novel_content") or project.get("novel_content") or ""
    if not text.strip():
        first = await db.video_sets.find_one({"project_id": project_id, "novel_content": {"$nin": [None, ""]}})
        text = (first or {}).get("novel_content") or ""
    if not text.strip():
        scripts = await db.scripts.find({"project_id": project_id}).to_list(None)
        text = "\n".join(str(d.get("line") or "") for sc in scripts for d in (sc.get("dialogues") or [])
                         if isinstance(d, dict))
    return text


@router.post("/{project_id}/style/suggest")
async def suggest_project_style(project_id: str, data: StyleSuggest, user: dict = Depends(get_current_user)):
    """风格 AI 识别：读小说片段，从风格库里推荐媒介和题材（模型失败时退回关键词规则）。
    apply=True 时写回作品（style_source=ai）；否则只返回推荐，由用户在风格页确认保存。"""
    from core.llm_factory import build_provider
    db = get_db()
    try:
        project = await db.projects.find_one({"_id": ObjectId(project_id), "user_id": str(user["_id"])})
    except Exception:
        raise HTTPException(status_code=400, detail="无效的项目ID")
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    text = (data.text or "").strip() or await _style_text(db, project, project_id, data.video_set_id, str(user["_id"]))
    if not text.strip():
        raise HTTPException(status_code=400, detail="还没有小说正文，先在小说页贴入内容再识别风格")
    try:
        llm = build_provider(user, data.model_id, data.model)
    except Exception:
        llm = None   # 没配模型 Key 也能用关键词规则给出结果
    s = await suggest_style(llm, text)
    if data.apply:
        fields = apply_fields(s)
        await db.projects.update_one({"_id": project["_id"]}, {"$set": fields})
        s = dict(s, applied=True, style_reason=fields["style_reason"])
    else:
        s = dict(s, applied=False)
    return ResponseModel(message=f"识别为 {s['medium_name']} · {s['genre_name']}", data=s)
