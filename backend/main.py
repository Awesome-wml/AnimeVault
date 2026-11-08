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
from api import video, prompt, video_set, model

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def _reset_loop_policy_for_threads():
    """线程里新建的事件循环改用标准 asyncio（见 lifespan 里的说明）。"""
    import asyncio
    policy = asyncio.get_event_loop_policy()
    if type(policy).__module__.startswith("uvloop"):
        asyncio.set_event_loop_policy(asyncio.DefaultEventLoopPolicy())
        logger.info("事件循环策略：主循环保持 uvloop，线程内新建循环改用标准 asyncio（Playwright 需要）")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时执行
    logger.info("🚀 启动DongAI后端服务...")

    # uvicorn[standard] 默认用 uvloop 并把它设成全局事件循环策略；
    # 豆包自动化在线程池里跑 Playwright 同步 API，会用该策略新建事件循环，
    # 在 uvloop 循环里启动浏览器会一直挂住（不报错、不超时）。
    # 主循环已经建好，这里把策略换回标准 asyncio，只影响之后线程里新建的循环。
    _reset_loop_policy_for_threads()
    
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
app.include_router(video.router)
app.include_router(prompt.router)
app.include_router(video_set.router)
app.include_router(model.router)


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
    import os
    os.environ.setdefault("MONGODB_URL", "mongodb://admin:dongai_mongo_2024@localhost:27017/")
    os.environ.setdefault("MONGODB_DB_NAME", "dongai")
    os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
    os.environ.setdefault("STATIC_DIR", os.path.join(os.path.dirname(__file__), "..", "static"))
    os.environ.setdefault("TZ", "Asia/Shanghai")
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True, loop="asyncio")
