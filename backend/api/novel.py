"""小说生成API"""
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse
from bson import ObjectId
import json
import logging
import re
from typing import Optional

from pydantic import BaseModel

from models.schema import NovelGenerate, NovelPolish, ResponseModel
from db.mongo_client import get_db
from api.auth import get_current_user
from core.providers.llm_provider import DoubaoLLMProvider
from core.llm_factory import build_provider
from core.prompt_registry import build_messages
from core.style_library import build_genre_rhythm, style_ref
from api.video_set import resolve_set

router = APIRouter(prefix="/api/novel", tags=["小说生成"])
logger = logging.getLogger(__name__)

# 润色人称选项 → 注入模板的人称要求
PERSON_RULES = {
    "first": "全文统一用第一人称“我”叙事（以主角视角），不切换到第三人称；内心活动用“我”来写。",
    "third": "全文统一用第三人称叙事，不切换到第一人称。",
}
DEFAULT_PERSON_RULE = "保持原文人称不变。"


def clean_novel_text(text: str) -> str:
    """把模型输出整理成纯正文：去 markdown 代码块；兼容旧模板输出的 {title, content} JSON。"""
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-zA-Z]*\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw).strip()
    if raw.startswith("{") and raw.endswith("}"):
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            obj = None
        if isinstance(obj, dict) and obj.get("content"):
            title = str(obj.get("title") or "").strip()
            content = str(obj["content"]).strip()
            return f"{title}\n\n{content}" if title else content
    return raw


def get_llm_provider(user: dict) -> DoubaoLLMProvider:
    """获取LLM提供者"""
    api_key = user.get("doubao_api_key")
    if not api_key:
        raise HTTPException(status_code=400, detail="请先配置API密钥（智谱免费模型glm-4.5-flash）")

    base_url = user.get("doubao_base_url", "https://open.bigmodel.cn/api/paas/v4")
    model = user.get("doubao_model", "glm-4.5-flash")
    return DoubaoLLMProvider(api_key=api_key, base_url=base_url, model=model)


@router.get("/generate")
async def generate_novel_get(
    project_id: str, genre: str, style: str, outline: str,
    protagonist: str, target_words: int = 5000, prompt_id: str = "",
    user: dict = Depends(get_current_user)
):
    data = NovelGenerate(project_id=project_id, genre=genre, style=style,
                          outline=outline, protagonist=protagonist,
                          target_words=target_words, prompt_id=prompt_id)
    return await _generate(data, user)

@router.post("/generate")
async def generate_novel(data: NovelGenerate, user: dict = Depends(get_current_user)):
    return await _generate(data, user)

async def _generate(data: NovelGenerate, user: dict = Depends(get_current_user)):
    """生成小说（SSE流式输出）"""
    db = get_db()
    
    # 检查项目权限
    try:
        project = await db.projects.find_one({
            "_id": ObjectId(data.project_id),
            "user_id": str(user["_id"])
        })
    except Exception:
        raise HTTPException(status_code=400, detail="无效的项目ID")
    
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    
    # 获取LLM提供者
    llm = get_llm_provider(user)
    
    # 构建提示词：骨架来自 system.json，约束来自 constraints.json，数据运行时填入
    messages = build_messages(
        "novel",
        variant=data.genre,
        genre=data.genre,
        style=data.style,
        outline=data.outline,
        protagonist=data.protagonist,
        target_words=data.target_words,
        genre_rhythm=build_genre_rhythm(**style_ref(project, genre=data.genre, style_id=data.style)),
    )
    
    # SSE流式响应
    async def event_generator():
        try:
            accumulated_content = ""
            
            async for chunk in await llm.chat(messages, stream=True):
                accumulated_content += chunk
                # 发送SSE事件
                yield f"data: {json.dumps({'type': 'chunk', 'content': chunk}, ensure_ascii=False)}\n\n"
            
            # 完成后保存：正文归到所属集；题材与风格仍是项目全局属性。
            novel_text = clean_novel_text(accumulated_content)
            set_doc = await resolve_set(db, data.project_id, data.video_set_id, str(user["_id"]))
            project_update = {"genre": data.genre, "style": data.style}
            if set_doc:
                await db.video_sets.update_one(
                    {"_id": set_doc["_id"]},
                    {"$set": {"novel_content": novel_text}}
                )
            else:
                # 老项目还没建集：兜底写项目级，等迁移/建集后归集
                project_update["novel_content"] = novel_text
            await db.projects.update_one(
                {"_id": ObjectId(data.project_id)},
                {"$set": project_update}
            )
            
            yield f"data: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"
            
        except Exception as e:
            error_msg = str(e)
            yield f"data: {json.dumps({'type': 'error', 'message': error_msg}, ensure_ascii=False)}\n\n"
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


class NovelSave(BaseModel):
    project_id: str
    video_set_id: Optional[str] = None
    content: str


@router.post("/save")
async def save_novel(
    body: Optional[NovelSave] = None,
    project_id: Optional[str] = None,
    video_set_id: Optional[str] = None,
    content: Optional[str] = None,
    user: dict = Depends(get_current_user)
):
    """保存小说内容。正文放 JSON 请求体；查询参数方式仅为兼容旧调用（长文放 URL 会触发 431）。"""
    if body is not None:
        project_id, video_set_id, content = body.project_id, body.video_set_id, body.content
    if not project_id or content is None:
        raise HTTPException(status_code=422, detail="缺少 project_id 或 content")
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

    # 正文归到所属集；老项目还没建集时兜底写项目级。
    set_doc = await resolve_set(db, project_id, video_set_id, str(user["_id"]))
    if set_doc:
        await db.video_sets.update_one(
            {"_id": set_doc["_id"]},
            {"$set": {"novel_content": content}}
        )
    else:
        await db.projects.update_one(
            {"_id": obj_id},
            {"$set": {"novel_content": content}}
        )

    return ResponseModel(message="保存成功")


@router.post("/polish")
async def polish_novel(data: NovelPolish, user: dict = Depends(get_current_user)):
    """小说润色/改编为漫剧文本：返回润色结果，不覆盖项目原文（由用户确认后再调用 /save）。"""
    db = get_db()

    try:
        project = await db.projects.find_one({
            "_id": ObjectId(data.project_id),
            "user_id": str(user["_id"])
        })
    except Exception:
        raise HTTPException(status_code=400, detail="无效的项目ID")
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    text = (data.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="待润色文本不能为空")

    llm = build_provider(user, data.model_id, data.model)
    person_rule = PERSON_RULES.get((data.person or "").strip().lower(), DEFAULT_PERSON_RULE)
    genre_rhythm = build_genre_rhythm(**style_ref(project))
    messages = build_messages(
        "novel_polish",
        variant=project.get("genre"),
        novel_text=text,
        person_rule=person_rule,
        genre_rhythm=genre_rhythm,
    )
    logger.info(f"[润色] project_id={data.project_id}, 原文 {len(text)} 字, 人称={data.person or '保持'}, 请求 {len(messages[-1]['content'])} 字")

    try:
        # 流式累积，避免长文本整段等待超时
        parts = []
        async for chunk in await llm.chat(messages, stream=True):
            parts.append(chunk)
    except Exception as e:
        logger.error(f"[润色] 失败: {type(e).__name__}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"润色失败: {str(e)}")

    polished = clean_novel_text("".join(parts))
    if not polished:
        raise HTTPException(status_code=500, detail="润色失败：模型没有返回内容")

    return ResponseModel(
        message="润色完成",
        data={"text": polished, "length": len(polished), "source_length": len(text)},
    )
