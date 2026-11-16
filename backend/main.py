"""FastAPI主应用"""
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from config import paths
from config.settings import settings, DEFAULT_JWT_SECRET
from core.frontend_mount import mount_frontend
from core.local_token import LocalTokenMiddleware
from core.license_guard import LicenseGuardMiddleware
from db.mongo_client import MongoDBClient
from db.redis_client import RedisClient
from utils.file_util import FileUtil

# 导入路由
from api import auth, project, novel, character, prop, scene, shot, image, tts, asset, config as config_api
from api import video, prompt, video_set, model, script, license as license_api

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
# 同时落盘到 backend/backend.log，便于排查流式/重试问题
try:
    _log_path = paths.log_file()
    _fh = logging.FileHandler(_log_path, encoding="utf-8")
    _fh.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
    logging.getLogger().addHandler(_fh)
except Exception:
    _fh = None
logger = logging.getLogger(__name__)


def _reset_loop_policy_for_threads():
    """线程里新建的事件循环改用标准 asyncio（见 lifespan 里的说明）。"""
    import asyncio
    policy = asyncio.get_event_loop_policy()
    if type(policy).__module__.startswith("uvloop"):
        asyncio.set_event_loop_policy(asyncio.DefaultEventLoopPolicy())
        logger.info("事件循环策略：主循环保持 uvloop，线程内新建循环改用标准 asyncio（Playwright 需要）")


def seed_builtin_data():
    """启动时的种子数据：内置模型预设（api/model.seed）。
    内置提示词已文件化到 core/prompts/（system.json + constraints.json），不再启动同步进 DB。
    失败只记日志，不阻止服务启动。"""
    try:
        model.seed()
    except Exception:
        logger.exception("内置模型预设补插失败")


def check_jwt_secret():
    """拒绝用默认密钥启动（桌面模式或 DONGAI_ALLOW_DEFAULT_SECRET=1 放行）。不在 import 阶段检查。"""
    import os
    if settings.JWT_SECRET != DEFAULT_JWT_SECRET:
        return
    if paths.is_desktop() or os.environ.get("DONGAI_ALLOW_DEFAULT_SECRET") == "1":
        return
    raise RuntimeError(
        "JWT_SECRET 仍是仓库默认值，拒绝启动。请设置环境变量 JWT_SECRET 为随机长字符串"
        "（如 `openssl rand -hex 32`）；仅本地开发可设 DONGAI_ALLOW_DEFAULT_SECRET=1 放行。")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时执行
    check_jwt_secret()
    logger.info("🚀 启动DongAI后端服务...")

    # uvicorn[standard] 默认用 uvloop 并把它设成全局事件循环策略；
    # 豆包自动化在线程池里跑 Playwright 同步 API，会用该策略新建事件循环，
    # 在 uvloop 循环里启动浏览器会一直挂住（不报错、不超时）。
    # 主循环已经建好，这里把策略换回标准 asyncio，只影响之后线程里新建的循环。
    _reset_loop_policy_for_threads()
    
    # 连接MongoDB
    await MongoDBClient.connect()
    await MongoDBClient.create_indexes()

    # 种子数据：内置提示词从代码同步进库、内置模型预设补插
    # （以前挂在 router.on_event("startup")，lifespan 应用下不会执行）
    seed_builtin_data()

    # 连接Redis（可选）
    await RedisClient.connect()
    
    # 确保静态文件目录存在
    FileUtil.get_images_dir()
    FileUtil.get_audio_dir()
    logger.info("✅ 静态文件目录已就绪")
    
    logger.info("✅ 后端服务启动完成")

    # 授权续租线程（桌面模式启用；非桌面模式仅 DONGAI_LICENSE_RENEW=1）
    try:
        from core import license_renewer
        license_renewer.start_if_enabled()
    except Exception:
        logger.exception("授权续租线程启动失败")

    yield
    
    # 关闭时执行
    logger.info("⏹️  关闭DongAI后端服务...")
    try:
        from core import license_renewer
        license_renewer.stop()
    except Exception:
        logger.exception("授权续租线程停止失败")
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

# 中间件顺序（先添加的在内层）：授权拦截 → 本地令牌 → CORS。
# 请求先过 CORS（预检由它处理），再过本地令牌，然后才是授权拦截，最后到业务。
app.add_middleware(LicenseGuardMiddleware)
app.add_middleware(LocalTokenMiddleware)

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
app.include_router(script.router)
app.include_router(license_api.router)


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


# 桌面模式：同源提供前端页面（DONGAI_FRONTEND_DIR 未设置时不做任何事）。必须在所有路由之后。
mount_frontend(app)


if __name__ == "__main__":
    import uvicorn
    import os
    if not os.environ.get("MONGODB_URL"):
        raise SystemExit("请先设置环境变量 MONGODB_URL（如 mongodb://user:密码@localhost:27017/），不再提供默认密码")
    os.environ.setdefault("MONGODB_DB_NAME", "dongai")
    os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
    os.environ.setdefault("STATIC_DIR", os.path.join(os.path.dirname(__file__), "..", "static"))
    os.environ.setdefault("TZ", "Asia/Shanghai")
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True, loop="asyncio")
