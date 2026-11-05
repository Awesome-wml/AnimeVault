"""道具管理API"""
from fastapi import APIRouter, HTTPException, Depends
from bson import ObjectId
from typing import List

from models.schema import PropCreate, PropUpdate, PropInfo, PropExtract, ResponseModel
from db.mongo_client import get_db
from api.auth import get_current_user
from core.providers.llm_provider import DoubaoLLMProvider
from core.prompt_tpl import PROP_EXTRACT_PROMPT
from core.prompt_store import get_prompt
from core.style_library import build_style_block
from utils.file_util import FileUtil

router = APIRouter(prefix="/api/props", tags=["道具管理"])


def get_llm_provider(user: dict) -> DoubaoLLMProvider:
    """获取LLM提供者"""
    api_key = user.get("doubao_api_key")
    if not api_key:
        raise HTTPException(status_code=400, detail="请先配置API密钥（智谱免费模型glm-4.7-flash）")

    base_url = user.get("doubao_base_url", "https://open.bigmodel.cn/api/paas/v4")
    model = user.get("doubao_model", "glm-4.7-flash")
    return DoubaoLLMProvider(api_key=api_key, base_url=base_url, model=model)


@router.post("/extract")
async def extract_props(data: PropExtract, user: dict = Depends(get_current_user)):
    """AI提取道具"""
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

    # 构建提示词（注入风格）
    style_block = build_style_block(data.style) if data.style else ""
    tpl = get_prompt("prop_extract", PROP_EXTRACT_PROMPT)
    prompt = tpl.format(
        novel_text=data.novel_text[:5000],
        style_block=style_block
    )
    messages = [{"role": "user", "content": prompt}]

    try:
        result = await llm.chat_json(messages)
        props = result.get("props", [])

        # 批量插入道具
        if props:
            prop_docs = [
                {
                    "user_id": str(user["_id"]),
                    "project_id": data.project_id,
                    "name": p["name"],
                    "prop_type": p.get("prop_type", ""),
                    "description": p.get("description", ""),
                    "image_path": None
                }
                for p in props
            ]
            await db.props.insert_many(prop_docs)

        return ResponseModel(
            message=f"成功提取{len(props)}个道具",
            data={"count": len(props), "props": props}
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"道具提取失败: {str(e)}")


@router.post("")
async def create_prop(data: PropCreate, user: dict = Depends(get_current_user)):
    """创建道具"""
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

    prop_doc = {
        "user_id": str(user["_id"]),
        "project_id": data.project_id,
        "name": data.name,
        "prop_type": data.prop_type,
        "description": data.description,
        "image_path": data.image_path
    }

    result = await db.props.insert_one(prop_doc)

    return ResponseModel(
        message="道具创建成功",
        data={"id": str(result.inserted_id)}
    )


@router.get("", response_model=List[PropInfo])
async def list_props(project_id: str, user: dict = Depends(get_current_user)):
    """获取道具列表"""
    db = get_db()

    cursor = db.props.find({
        "user_id": str(user["_id"]),
        "project_id": project_id
    })
    props = await cursor.to_list(length=100)

    return [
        PropInfo(
            id=str(p["_id"]),
            user_id=p["user_id"],
            project_id=p["project_id"],
            name=p["name"],
            prop_type=p.get("prop_type"),
            description=p.get("description"),
            image_path=p.get("image_path")
        )
        for p in props
    ]


@router.put("/{prop_id}")
async def update_prop(
    prop_id: str,
    data: PropUpdate,
    user: dict = Depends(get_current_user)
):
    """更新道具"""
    db = get_db()

    try:
        obj_id = ObjectId(prop_id)
    except Exception:
        raise HTTPException(status_code=400, detail="无效的道具ID")

    # 检查权限
    prop = await db.props.find_one({
        "_id": obj_id,
        "user_id": str(user["_id"])
    })

    if not prop:
        raise HTTPException(status_code=404, detail="道具不存在")

    # 构建更新数据
    update_data = {}
    if data.name is not None:
        update_data["name"] = data.name
    if data.prop_type is not None:
        update_data["prop_type"] = data.prop_type
    if data.description is not None:
        update_data["description"] = data.description
    if data.image_path is not None:
        update_data["image_path"] = data.image_path

    if update_data:
        await db.props.update_one(
            {"_id": obj_id},
            {"$set": update_data}
        )

    return ResponseModel(message="道具更新成功")


@router.delete("/{prop_id}")
async def delete_prop(prop_id: str, user: dict = Depends(get_current_user)):
    """删除道具"""
    db = get_db()

    try:
        obj_id = ObjectId(prop_id)
    except Exception:
        raise HTTPException(status_code=400, detail="无效的道具ID")

    # 检查权限
    prop = await db.props.find_one({
        "_id": obj_id,
        "user_id": str(user["_id"])
    })

    if not prop:
        raise HTTPException(status_code=404, detail="道具不存在")

    # 删除关联图片
    if prop.get("image_path"):
        FileUtil.delete_file(prop["image_path"])

    await db.props.delete_one({"_id": obj_id})

    return ResponseModel(message="道具删除成功")
