"""剧本管理API：小说 → 分场剧本 → 落库"""
import logging
from fastapi import APIRouter, HTTPException, Depends
from bson import ObjectId
from typing import List, Optional

from models.schema import ScriptConvert, ScriptCreate, ScriptInfo, ScriptUpdate, ScriptDialogue, ResponseModel
from db.mongo_client import get_db
from api.auth import get_current_user
from core.prompt_tpl import SCRIPT_CONVERT_PROMPT, SCRIPT_CONVERT_COMMON_RULES
from core.llm_factory import build_provider, resolve_prompt, safe_format
from core.style_library import build_style_block
from core.sse import run_with_sse

router = APIRouter(prefix="/api/scripts", tags=["剧本管理"])
logger = logging.getLogger(__name__)


def _dialogues_to_list(dialogues) -> List[dict]:
    out = []
    for d in (dialogues or []):
        if isinstance(d, dict):
            speaker = (d.get("speaker") or "").strip()
            line = (d.get("line") or "").strip()
            if line:
                out.append({"speaker": speaker or "旁白", "line": line})
    return out


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

    logger.info(f"[剧本] 收到转剧本请求: project_id={data.project_id}, 小说 {len(data.novel_text or '')} 字")
    llm = build_provider(user, data.model_id, data.model)
    logger.info(f"[剧本] 使用模型: model_id={data.model_id or '全局默认'}, model={data.model or '默认'}")

    style_id = project.get("style")
    style_block = build_style_block(style_id) if style_id else ""
    tpl = resolve_prompt(
        data.prompt_id, "script_convert", SCRIPT_CONVERT_PROMPT,
        category=project.get("genre"),
    )
    prompt = safe_format(
        tpl,
        novel_paragraph=data.novel_text[:5000],
        style_block=style_block,
        common_rules=SCRIPT_CONVERT_COMMON_RULES,
    )
    logger.info(f"[剧本] 提示词已组装: 模板 {len(tpl)} 字, 最终请求 {len(prompt)} 字, prompt_id={data.prompt_id or '默认'}")
    messages = [{"role": "user", "content": prompt}]

    async def build_task(report):
        logger.info("[剧本] 开始调用大模型转剧本...")
        result = await llm.chat_json(messages, on_progress=report)

        scenes = result.get("scenes", []) or []
        logger.info(f"[剧本] 模型返回 {len(scenes)} 场")

        # 覆盖旧剧本
        await db.scripts.delete_many({"project_id": data.project_id})

        docs = []
        for idx, sc in enumerate(scenes):
            if not isinstance(sc, dict):
                continue
            docs.append({
                "user_id": user_id,
                "project_id": data.project_id,
                "scene_no": sc.get("scene_no", idx + 1),
                "location": sc.get("location", ""),
                "time": sc.get("time", ""),
                "characters": [c for c in (sc.get("characters") or []) if c],
                "dialogues": _dialogues_to_list(sc.get("dialogues")),
                "action": sc.get("action", ""),
                "beat": sc.get("beat", ""),
                "summary": sc.get("summary", ""),
            })

        if docs:
            await db.scripts.insert_many(docs)
        logger.info(f"[剧本] 已落库 {len(docs)} 场到项目 {data.project_id}")

        return f"剧本转换完成：{len(docs)} 场", {"count": len(docs)}

    return await run_with_sse(build_task)


@router.get("/list")
async def list_scripts(project_id: str, user: dict = Depends(get_current_user)):
    """列出项目下的剧本场次。"""
    db = get_db()
    cursor = db.scripts.find({"project_id": project_id, "user_id": str(user["_id"])}).sort("scene_no", 1)
    scripts = []
    for s in await cursor.to_list(None):
        scripts.append(ScriptInfo(
            id=str(s["_id"]),
            project_id=s["project_id"],
            scene_no=s.get("scene_no", 0),
            location=s.get("location"),
            time=s.get("time"),
            characters=s.get("characters") or [],
            dialogues=[ScriptDialogue(**d) for d in (s.get("dialogues") or [])],
            action=s.get("action"),
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
    last = await db.scripts.find({"project_id": data.project_id}).sort("scene_no", -1).limit(1).to_list(1)
    doc = {
        "user_id": user_id,
        "project_id": data.project_id,
        "scene_no": int(last[0].get("scene_no") or 0) + 1 if last else 1,
        "location": data.location or "",
        "time": data.time or "",
        "characters": [c for c in (data.characters or []) if c],
        "dialogues": _dialogues_to_list([d.dict() for d in (data.dialogues or [])]),
        "action": data.action or "",
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
