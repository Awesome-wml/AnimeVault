"""FastAPI主应用"""
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from config.settings import settings
from db.mongo_client import MongoDBClient
from db.redis_client import RedisClient
from utils.file_util import FileUtil

# 导入路由
from api import auth, project, novel, character, prop, scene, shot, image, tts, asset, config as config_api
# video 模块需要 playwright，暂时注释
# from api import video

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时执行
    logger.info("🚀 启动DongAI后端服务...")
    
    # 连接MongoDB
    await MongoDBClient.connect()
    await MongoDBClient.create_indexes()
    
    # 连接Redis（可选）
    await RedisClient.connect()
    
    # 确保静态文件目录存在
    FileUtil.get_images_dir()
    FileUtil.get_audio_dir()
    logger.info("✅ 静态文件目录已就绪")
    
    logger.info("✅ 后端服务启动完成")
    
    yield
    
    # 关闭时执行
    logger.info("⏹️  关闭DongAI后端服务...")
    await MongoDBClient.close()
    await RedisClient.close()
    logger.info("✅ 后端服务已关闭")


# 创建FastAPI应用
app = FastAPI(
    title="DongAI短剧工作台",
    description="对标梦源AI的短剧创作平台",
    version="1.0.0",
    lifespan=lifespan
)

# CORS中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 挂载静态文件
static_dir = Path(settings.STATIC_DIR)
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
    logger.info(f"✅ 静态文件目录挂载: {static_dir}")

# 注册路由
app.include_router(auth.router)
app.include_router(project.router)
app.include_router(novel.router)
app.include_router(character.router)
app.include_router(prop.router)
app.include_router(scene.router)
app.include_router(shot.router)
app.include_router(image.router)
app.include_router(asset.router)
app.include_router(tts.router)
app.include_router(config_api.router)
# app.include_router(video.router)  # 需要 playwright，暂时禁用


@app.get("/")
async def root():
    """根路径"""
    return {
        "app": "DongAI短剧工作台",
        "version": "1.0.0",
        "docs": "/docs"
    }


@app.get("/health")
async def health():
    """健康检查"""
    return {
        "status": "healthy",
        "mongodb": "connected" if MongoDBClient.db is not None else "disconnected",
        "redis": "connected" if RedisClient.enabled else "disabled"
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
