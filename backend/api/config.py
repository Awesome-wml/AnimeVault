"""系统配置API"""
from fastapi import APIRouter
from models.schema import ResponseModel
from core.video_models import DEFAULT_VIDEO_MODEL_KEY, list_video_models

router = APIRouter(prefix="/api/config", tags=["系统配置"])


@router.get("/system")
async def get_system_config():
    """获取系统配置"""
    return ResponseModel(
        data={
            "app_name": "DongAI短剧工作台",
            "version": "1.0.0",
            "features": {
                "llm": True,
                "image_gen": True,
                "tts": True,
                "video_gen": False  # 预留扩展
            }
        }
    )


@router.get("/video-models")
async def get_video_models():
    """豆包网页视频生成可选模型（Seedance 系列）：时长范围、额度倍数、可传的参考素材类型。"""
    return ResponseModel(data={"models": list_video_models(), "default": DEFAULT_VIDEO_MODEL_KEY})
