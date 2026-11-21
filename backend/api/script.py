"""剧本管理API：小说 → 分场剧本 → 落库"""
import logging
from fastapi import APIRouter, HTTPException, Depends
from bson import ObjectId
from typing import List, Optional

from models.schema import ScriptConvert, ScriptCreate, ScriptInfo, ScriptUpdate, ScriptDialogue, ResponseModel
from db.mongo_client import get_db
from api.auth import get_current_user
from config.settings import settings
from core.prompt_tpl import (SCRIPT_PERSON_RULES, DEFAULT_SCRIPT_PERSON,
                             script_length_rule)
from core.llm_factory import build_provider
from core.prompt_registry import build_messages, resolve_prompt
from core.script_text import clean_dialogues, clean_shot_hint, merge_chunk_scenes, script_chunk_note
from core.shot_split import split_novel_chunks
from core.style_library import build_genre_rhythm, build_style_block, style_ref
from core.sse import run_with_sse
from core.style_suggest import auto_style_if_needed
from core.video_models import get_video_model
from api.video_set import resolve_set

router = APIRouter(prefix="/api/scripts", tags=["剧本管理"])
logger = logging.getLogger(__name__)
MAX_SCRIPT_CHARS = 60000   # 一次转剧本最多处理的小说字数（按 SCRIPT_CHUNK_CHARS 分块，约 15 块）


def _dialogues_to_list(dialogues) -> List[dict]:
    """落库前规整台词：丢空台词，kind 兜底（旁白 → narration，缺省按说话人推断）。"""
    return clean_dialogues(dialogues)


def resolve_person(value: Optional[str], project: dict) -> str:
    """请求 > 项目设置 > 默认 keep；不认识的值按 keep。"""
    for v in (value, project.get("script_person")):
        v = (v or "").strip().lower()
        if v in SCRIPT_PERSON_RULES:
            return v
    return DEFAULT_SCRIPT_PERSON


def resolve_target_seconds(value: Optional[int], project: dict) -> int:
    """请求里明确给了（含 0 = 不限定）就用请求的；没给用项目设置；都没有为 0（按原文三成）。"""
    if value is not None:
        return max(int(value), 0)
    return max(int(project.get("script_target_seconds") or 0), 0)


def build_script_prompts(key: str, variant: str, novel: str, *, style_block: str, genre_rhythm: str, person: str,
                         target_seconds: int, chunk_chars: int, segment_seconds: float = 15.0) -> list:
    """长文按段落分块（不在句中切），返回 [(块文本, render(prev) → messages)]；目标时长按块字数比例分摊。"""
    novel = (novel or "").strip()
    chunks = split_novel_chunks(novel, chunk_chars) or [novel]
    total_chars = max(sum(len(c) for c in chunks), 1)
    prompts = []
    for i, chunk in enumerate(chunks, start=1):
        share = round(target_seconds * len(chunk) / total_chars) if target_seconds else 0
        prompts.append((chunk, lambda prev, i=i, chunk=chunk, share=share: build_messages(
            key, variant=variant,
            novel_paragraph=chunk,
            style_block=style_block,
            genre_rhythm=genre_rhythm,
            person_rule=SCRIPT_PERSON_RULES[person],
            length_rule=script_length_rule(len(chunk), share, segment_seconds),
            chunk_note=script_chunk_note(i, len(chunks), prev),
        )))
    return prompts


@router.post("/convert")
async def convert_script(data: ScriptConvert, user: dict = Depends(get_current_user)):
    """把小说段落转成分场剧本并落库（覆盖旧剧本），SSE 流式推进度。"""
    db = get_db()
    user_id = str(user["_id"])

    try:
        project = await db.projects.find_one({
            "_id": ObjectId(data.project_id),
            "user_id": user_id
        })
    except Exception:
        raise HTTPException(status_code=400, detail="无效的项目ID")
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    set_doc = await resolve_set(db, data.project_id, data.video_set_id, user_id)
    set_id = str(set_doc["_id"]) if set_doc else None

    if not (data.novel_text or "").strip():
        raise HTTPException(status_code=400, detail="小说内容为空")
    if len(data.novel_text) > MAX_SCRIPT_CHARS:
        raise HTTPException(status_code=400, detail=f"小说超过 {MAX_SCRIPT_CHARS} 字，请分集转剧本")
    logger.info(f"[剧本] 收到转剧本请求: project_id={data.project_id}, 小说 {len(data.novel_text or '')} 字")
    llm = build_provider(user, data.model_id, data.model)
    logger.info(f"[剧本] 使用模型: model_id={data.model_id or '全局默认'}, model={data.model or '默认'}")

    # 新建时没选风格的作品：第一次用到风格前先按正文自动识别（core/style_suggest.py），之后全链路照它出图出视频
    await auto_style_if_needed(db, project, llm, data.novel_text)
    style = style_ref(project)  # 媒介 + 题材（旧项目只有 style 时自动映射）
    style_block = build_style_block(**style)
    person = resolve_person(data.person, project)
    target_seconds = resolve_target_seconds(data.target_seconds, project)
    prompt_key, prompt_variant = resolve_prompt(data.prompt_id, "script_convert")
    parts = build_script_prompts(
        prompt_key, prompt_variant if prompt_variant is not None else project.get("genre"),
        data.novel_text, style_block=style_block,
        genre_rhythm=build_genre_rhythm(**style),
        person=person, target_seconds=target_seconds, chunk_chars=settings.SCRIPT_CHUNK_CHARS,
        segment_seconds=get_video_model(project.get("video_model"))["max_duration"],
    )
    total = len(parts)
    logger.info(f"[剧本] prompt_id={data.prompt_id or '默认'}, 人称 {person}, "
                f"目标时长 {target_seconds or '不限定（约原文三成）'}, 分 {total} 块：{[len(c) for c, _ in parts]}")

    async def build_task(report):
        results: List[list] = []
        received = 0
        for i, (chunk, render) in enumerate(parts, start=1):
            prev = results[-1][-1] if results and results[-1] else None
            messages = render(prev)
            logger.info(f"[剧本] 第 {i}/{total} 块（{len(chunk)} 字）开始调用大模型...")
            base = received

            async def on_progress(chars, base=base, i=i):
                await report(base + chars, chunk=i, total=total)
            await report(base, chunk=i, total=total)
            result = await llm.chat_json(messages, on_progress=on_progress)
            scenes = [sc for sc in (result.get("scenes") or []) if isinstance(sc, dict)] if isinstance(result, dict) else []
            logger.info(f"[剧本] 第 {i}/{total} 块返回 {len(scenes)} 场")
            results.append(scenes)
            received = base + sum(len(str(sc)) for sc in scenes)

        scenes = merge_chunk_scenes(results)
        # 覆盖本集旧剧本
        await db.scripts.delete_many({"project_id": data.project_id, "video_set_id": set_id})

        docs = [{
            "user_id": user_id,
            "project_id": data.project_id,
            "video_set_id": set_id,
            "scene_no": sc["scene_no"],
            "location": sc.get("location", "") or "",
            "time": sc.get("time", "") or "",
            "characters": sc.get("characters") or [],
            "dialogues": sc.get("dialogues") or [],
            "action": sc.get("action", "") or "",
            "shot_hint": clean_shot_hint(sc.get("shot_hint")),
            "beat": sc.get("beat", "") or "",
            "summary": sc.get("summary", "") or "",
        } for sc in scenes]

        if docs:
            await db.scripts.insert_many(docs)
        logger.info(f"[剧本] 已落库 {len(docs)} 场到项目 {data.project_id}")
        msg = f"剧本转换完成：{len(docs)} 场" + (f"（分 {total} 块转换）" if total > 1 else "")
        return msg, {"count": len(docs), "chunks": total}

    return await run_with_sse(build_task, key=f"script:{data.project_id}:{set_id or 'default'}", owner=user_id, kind="转剧本")


@router.get("/list")
async def list_scripts(project_id: str, video_set_id: str = "", user: dict = Depends(get_current_user)):
    """列出指定集下的剧本场次；不传集数时取项目第一集。"""
    db = get_db()
    query = {"project_id": project_id, "user_id": str(user["_id"])}
    if video_set_id:
        query["video_set_id"] = video_set_id
    else:
        set_doc = await resolve_set(db, project_id, "", str(user["_id"]))
        if set_doc:
            query["video_set_id"] = str(set_doc["_id"])
    cursor = db.scripts.find(query).sort("scene_no", 1)
    scripts = []
    for s in await cursor.to_list(None):
        scripts.append(ScriptInfo(
            id=str(s["_id"]),
            project_id=s["project_id"],
            video_set_id=s.get("video_set_id"),
            scene_no=s.get("scene_no", 0),
            location=s.get("location"),
            time=s.get("time"),
            characters=s.get("characters") or [],
            dialogues=[ScriptDialogue(**d) for d in clean_dialogues(s.get("dialogues"))],
            action=s.get("action"),
            shot_hint=s.get("shot_hint") or "",
            beat=s.get("beat"),
            summary=s.get("summary"),
        ).dict())
    return ResponseModel(data={"scripts": scripts})


@router.post("")
async def create_script(data: ScriptCreate, user: dict = Depends(get_current_user)):
    """手动新增一场（追加到最后，场次号接着编）。"""
    db = get_db()
    user_id = str(user["_id"])
    try:
        project = await db.projects.find_one({"_id": ObjectId(data.project_id), "user_id": user_id})
    except Exception:
        raise HTTPException(status_code=400, detail="无效的项目ID")
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    set_doc = await resolve_set(db, data.project_id, data.video_set_id, user_id)
    set_id = str(set_doc["_id"]) if set_doc else None
    last = await db.scripts.find({"project_id": data.project_id, "video_set_id": set_id}).sort("scene_no", -1).limit(1).to_list(1)
    doc = {
        "user_id": user_id,
        "project_id": data.project_id,
        "video_set_id": set_id,
        "scene_no": int(last[0].get("scene_no") or 0) + 1 if last else 1,
        "location": data.location or "",
        "time": data.time or "",
        "characters": [c for c in (data.characters or []) if c and str(c).strip() != "旁白"],
        "dialogues": _dialogues_to_list([d.dict() for d in (data.dialogues or [])]),
        "action": data.action or "",
        "shot_hint": clean_shot_hint(data.shot_hint),
        "beat": data.beat or "",
        "summary": data.summary or "",
    }
    r = await db.scripts.insert_one(doc)
    return ResponseModel(message="已新增一场", data={"id": str(r.inserted_id), "scene_no": doc["scene_no"]})


@router.put("/{script_id}")
async def update_script(script_id: str, data: ScriptUpdate, user: dict = Depends(get_current_user)):
    """编辑剧本场次。"""
    db = get_db()
    user_id = str(user["_id"])
    try:
        obj_id = ObjectId(script_id)
    except Exception:
        raise HTTPException(status_code=400, detail="无效的场次ID")

    update = {k: v for k, v in data.dict().items() if v is not None}
    if "shot_hint" in update:
        update["shot_hint"] = clean_shot_hint(update["shot_hint"])
    if "dialogues" in update and update["dialogues"] is not None:
        update["dialogues"] = _dialogues_to_list(update["dialogues"])

    result = await db.scripts.update_one(
        {"_id": obj_id, "user_id": user_id},
        {"$set": update},
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="场次不存在")
    return ResponseModel(message="场次已更新")


@router.delete("/{script_id}")
async def delete_script(script_id: str, user: dict = Depends(get_current_user)):
    """删除单个场次。"""
    db = get_db()
    user_id = str(user["_id"])
    try:
        obj_id = ObjectId(script_id)
    except Exception:
        raise HTTPException(status_code=400, detail="无效的场次ID")
    result = await db.scripts.delete_one({"_id": obj_id, "user_id": user_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="场次不存在")
    return ResponseModel(message="场次已删除")
