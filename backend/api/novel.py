"""小说生成API"""
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse
from bson import ObjectId
import json

from models.schema import NovelGenerate, ResponseModel
from db.mongo_client import get_db
from api.auth import get_current_user
from core.providers.llm_provider import DoubaoLLMProvider
from core.prompt_tpl import NOVEL_GENERATE_PROMPT

router = APIRouter(prefix="/api/novel", tags=["小说生成"])


def get_llm_provider(user: dict) -> DoubaoLLMProvider:
    """获取LLM提供者"""
    api_key = user.get("doubao_api_key")
    if not api_key:
        raise HTTPException(status_code=400, detail="请先配置API密钥（智谱免费模型glm-4.7-flash）")

    base_url = user.get("doubao_base_url", "https://open.bigmodel.cn/api/paas/v4")
    model = user.get("doubao_model", "glm-4.7-flash")
    return DoubaoLLMProvider(api_key=api_key, base_url=base_url, model=model)


@router.post("/generate")
async def generate_novel(data: NovelGenerate, user: dict = Depends(get_current_user)):
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
    
    # 构建提示词
    prompt = NOVEL_GENERATE_PROMPT.format(
        genre=data.genre,
        style=data.style,
        outline=data.outline,
        protagonist=data.protagonist,
        target_words=data.target_words
    )
    
    messages = [
        {"role": "user", "content": prompt}
    ]
    
    # SSE流式响应
    async def event_generator():
        try:
            accumulated_content = ""
            
            async for chunk in await llm.chat(messages, stream=True):
                accumulated_content += chunk
                # 发送SSE事件
                yield f"data: {json.dumps({'type': 'chunk', 'content': chunk}, ensure_ascii=False)}\n\n"
            
            # 完成后保存到项目（同时写入题材与风格，成为项目全局属性）
            await db.projects.update_one(
                {"_id": ObjectId(data.project_id)},
                {"$set": {
                    "novel_content": accumulated_content,
                    "genre": data.genre,
                    "style": data.style
                }}
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


@router.post("/save")
async def save_novel(
    project_id: str,
    content: str,
    user: dict = Depends(get_current_user)
):
    """保存小说内容"""
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
    
    # 保存内容
    await db.projects.update_one(
        {"_id": obj_id},
        {"$set": {"novel_content": content}}
    )
    
    return ResponseModel(message="保存成功")
