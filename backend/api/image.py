"""文生图API"""
from fastapi import APIRouter, HTTPException, Depends
from bson import ObjectId

from models.schema import ImageGenerate, ResponseModel
from db.mongo_client import get_db
from api.auth import get_current_user
from core.llm_factory import build_image_provider
from core.providers.image_provider import DoubaoImageProvider, image_size
from core.style_library import build_style_art_prompt
from utils.file_util import FileUtil

router = APIRouter(prefix="/api/image", tags=["文生图"])


def get_image_provider(user: dict, model_id: str = None, model: str = None) -> DoubaoImageProvider:
    """获取图像生成提供者：优先读 image 类型模型预设，空 Key 回退账号全局密钥。"""
    return build_image_provider(user, model_id, model)


@router.post("/generate")
async def generate_image(data: ImageGenerate, user: dict = Depends(get_current_user)):
    """生成图片"""
    db = get_db()
    
    # 检查分镜权限
    try:
        shot = await db.shots.find_one({
            "_id": ObjectId(data.shot_id),
            "user_id": str(user["_id"])
        })
    except Exception:
        raise HTTPException(status_code=400, detail="无效的分镜ID")
    
    if not shot:
        raise HTTPException(status_code=404, detail="分镜不存在")
    
    # 获取图像生成提供者（按所选模型预设/子模型）
    image_provider = get_image_provider(user, data.model_id, data.model)

    # 读取分镜所属项目的风格，注入绘画指令保证画面统一
    project = await db.projects.find_one({"_id": shot.get("project_id")}) if shot.get("project_id") else None
    style_id = project.get("style") if project else None
    art_style = build_style_art_prompt(style_id) if style_id else ""
    final_prompt = data.prompt
    if art_style and art_style not in final_prompt:
        final_prompt = final_prompt + ", " + art_style

    try:
        # 按所选模型档位取合规横屏尺寸
        gen_w, gen_h = image_size(image_provider.model, "landscape")
        image_data = await image_provider.generate_image(
            prompt=final_prompt,
            neg_prompt=data.neg_prompt,
            width=gen_w,
            height=gen_h
        )
        
        # 保存图片
        img_path = FileUtil.save_image(image_data, ext="png")
        
        # 更新分镜记录
        await db.shots.update_one(
            {"_id": ObjectId(data.shot_id)},
            {"$set": {"img_path": img_path}}
        )
        
        return ResponseModel(
            message="图片生成成功",
            data={"img_path": img_path}
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"图片生成失败: {str(e)}")
