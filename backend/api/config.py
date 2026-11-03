"""系统配置API"""
from fastapi import APIRouter
from models.schema import ResponseModel

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
