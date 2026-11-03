"""资产参考图生成API：角色三视图、道具图、场景图"""
from fastapi import APIRouter, HTTPException, Depends, UploadFile, File
from bson import ObjectId
from pydantic import BaseModel, Field
from typing import Optional

from models.schema import ResponseModel
from db.mongo_client import get_db
from api.auth import get_current_user
from core.providers.image_provider import DoubaoImageProvider
from core.prompt_tpl import CHARACTER_SHEET_PROMPT
from core.style_library import build_style_art_prompt
from utils.file_util import FileUtil

router = APIRouter(prefix="/api/assets", tags=["资产参考图"])


class AssetGenerate(BaseModel):
    """生成资产参考图请求"""
    asset_type: str = Field(..., description="资产类型：character/prop/scene")
    asset_id: str = Field(..., description="资产ID（角色/道具/场景）")
    style: Optional[str] = None  # 风格ID
    prompt_override: Optional[str] = None  # 可选：覆盖默认提示词


def get_image_provider(user: dict) -> DoubaoImageProvider:
    """获取图像生成提供者（智谱免费文生图glm-image）"""
    api_key = user.get("doubao_api_key")
    if not api_key:
        raise HTTPException(status_code=400, detail="请先配置API密钥（智谱免费文生图glm-image）")

    base_url = user.get("doubao_base_url", "https://open.bigmodel.cn/api/paas/v4")
    model = user.get("doubao_image_model", "glm-image")
    return DoubaoImageProvider(api_key=api_key, base_url=base_url, model=model)


async def _get_asset(db, asset_type: str, asset_id: str, user_id: str):
    """获取资产文档并校验权限"""
    try:
        obj_id = ObjectId(asset_id)
    except Exception:
        raise HTTPException(status_code=400, detail="无效的资产ID")

    collection_map = {
        "character": db.characters,
        "prop": db.props,
        "scene": db.scenes,
    }
    collection = collection_map.get(asset_type)
    if collection is None:
        raise HTTPException(status_code=400, detail=f"不支持的资产类型: {asset_type}")

    asset = await collection.find_one({"_id": obj_id, "user_id": user_id})
    if asset is None:
        raise HTTPException(status_code=404, detail="资产不存在")
    return asset


@router.post("/generate")
async def generate_asset_image(data: AssetGenerate, user: dict = Depends(get_current_user)):
    """生成资产参考图（角色三视图/道具图/场景图）"""
    db = get_db()
    user_id = str(user["_id"])

    # 获取资产
    asset = await _get_asset(db, data.asset_type, data.asset_id, user_id)
    name = asset.get("name", "")
    description = asset.get("description", "")
    art_style = build_style_art_prompt(data.style)

    image_provider = get_image_provider(user)

    try:
        # 构建提示词
        if data.prompt_override:
            prompt = data.prompt_override
        elif data.asset_type == "character":
            # 角色三视图：一张图含正面/侧面/背面
            prompt = CHARACTER_SHEET_PROMPT.format(
                character_name=name,
                character_description=description,
                art_style=art_style
            )
        else:
            # 道具/场景参考图
            type_label = "道具" if data.asset_type == "prop" else "场景"
            style_suffix = f"，风格指令：{art_style}" if art_style else ""
            prompt = (
                f"一张{type_label}参考图。"
                f"{type_label}名称：{name}。"
                f"{type_label}描述：{description}。"
                f"构图居中、主体清晰、浅色纯背景，适合作为参考图。"
                f"{style_suffix}"
            )

        # 生成图片
        image_data = await image_provider.generate_image(prompt=prompt)

        # 保存图片
        img_path = FileUtil.save_image(image_data, ext="png")

        # 更新资产记录
        collection_map = {
            "character": db.characters,
            "prop": db.props,
            "scene": db.scenes,
        }
        await collection_map[data.asset_type].update_one(
            {"_id": ObjectId(data.asset_id)},
            {"$set": {"image_path": img_path}}
        )

        return ResponseModel(
            message=f"{name} 参考图生成成功",
            data={"img_path": img_path}
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"参考图生成失败: {str(e)}")

@router.post("/upload")
async def upload_asset_image(
    asset_type: str,
    asset_id: str,
    file: UploadFile = File(...),
    user: dict = Depends(get_current_user),
):
    """人工上传资产参考图（角色三视图/道具图/场景图），保存并写回 image_path"""
    db = get_db()
    user_id = str(user["_id"])

    # 校验资产
    asset = await _get_asset(db, asset_type, asset_id, user_id)
    name = asset.get("name", "")

    # 校验文件类型
    content_type = file.content_type or ""
    if not (content_type.startswith("image/")):
        raise HTTPException(status_code=400, detail="只支持上传图片文件")

    # 读取文件内容
    try:
        data = await file.read()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"读取上传文件失败: {str(e)}")
    if not data:
        raise HTTPException(status_code=400, detail="上传文件为空")

    # 确定扩展名
    ext_map = {
        "image/png": "png",
        "image/jpeg": "jpg",
        "image/webp": "webp",
        "image/gif": "gif",
    }
    ext = ext_map.get(content_type, "png")

    # 保存图片
    img_path = FileUtil.save_image(data, ext=ext)

    # 写回资产记录
    collection_map = {
        "character": db.characters,
        "prop": db.props,
        "scene": db.scenes,
    }
    await collection_map[asset_type].update_one(
        {"_id": ObjectId(asset_id)},
        {"$set": {"image_path": img_path}}
    )

    return ResponseModel(
        message=f"{name} 参考图上传成功",
        data={"img_path": img_path}
    )
