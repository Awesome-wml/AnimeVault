"""文生图API"""
from fastapi import APIRouter, HTTPException, Depends
from bson import ObjectId

from models.schema import ImageGenerate, ResponseModel
from db.mongo_client import get_db
from api.auth import get_current_user
from core.providers.image_provider import DoubaoImageProvider
from core.style_library import build_style_art_prompt
from utils.file_util import FileUtil

router = APIRouter(prefix="/api/image", tags=["文生图"])


def get_image_provider(user: dict) -> DoubaoImageProvider:
    """获取图像生成提供者（智谱免费文生图glm-image）"""
    api_key = user.get("doubao_api_key")
    if not api_key:
        raise HTTPException(status_code=400, detail="请先配置API密钥（智谱免费文生图glm-image）")

    base_url = user.get("doubao_base_url", "https://open.bigmodel.cn/api/paas/v4")
    model = user.get("doubao_image_model", "glm-image")
    return DoubaoImageProvider(api_key=api_key, base_url=base_url, model=model)


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
    
    # 获取图像生成提供者
    image_provider = get_image_provider(user)

    # 读取分镜所属项目的风格，注入绘画指令保证画面统一
    project = None
    if shot.get("project_id") and ObjectId.is_valid(shot["project_id"]):
        # 分镜里 project_id 存的是字符串，必须转回 ObjectId 才能查到项目
        project = await db.projects.find_one({"_id": ObjectId(shot["project_id"])})
    style_id = project.get("style") if project else None
    art_style = build_style_art_prompt(style_id) if style_id else ""
    final_prompt = data.prompt
    if art_style and art_style not in final_prompt:
        final_prompt = final_prompt + ", " + art_style

    try:
        # 生成图片（3:2 横屏比例，匹配分镜预览显示）
        image_data = await image_provider.generate_image(
            prompt=final_prompt,
            neg_prompt=data.neg_prompt,
            width=1280,
            height=856
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
