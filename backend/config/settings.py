from pydantic_settings import BaseSettings
from typing import List
import os

from config import paths

DEFAULT_JWT_SECRET = "your-secret-key-please-change-this"


class Settings(BaseSettings):
    """全局配置"""
    
    # MongoDB配置
    MONGODB_URL: str = "mongodb://localhost:27017/"
    MONGODB_DB_NAME: str = "dongai"
    
    # Redis配置（可选）
    REDIS_URL: str = "redis://localhost:6379/0"
    
    # 静态文件目录
    STATIC_DIR: str = "../static"
    
    # JWT配置
    JWT_SECRET: str = DEFAULT_JWT_SECRET
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 43200  # 30天
    
    # CORS配置
    CORS_ORIGINS: str = "http://localhost:8080,http://localhost:3000"

    # 剪映草稿目录（默认macOS路径，可用环境变量覆盖）
    JIANYING_DRAFT_DIR: str = ""  # 空则自动检测
    # 剪映草稿模板目录（含 draft_info.json / draft_meta_info.json），空则用 backend/.jianying_template
    JIANYING_TEMPLATE_DIR: str = ""

    # 国际版 CapCut 草稿目录（空则自动检测 macOS 默认路径）
    CAPCUT_DRAFT_DIR: str = ""
    # CapCut 草稿模板目录（含 draft_info.json / draft_meta_info.json），空则用 backend/.capcut_template
    CAPCUT_TEMPLATE_DIR: str = ""

    # 角色设定板脸部/皮肤线框网格后处理（弱化真人肖像识别度，零第三方依赖）
    FACE_GRID_ENABLED: bool = True
    FACE_GRID_CELL: int = 22       # 网格单元边长（像素），越小越密
    FACE_GRID_ALPHA: int = 70      # 网格不透明度 0-255
    FACE_GRID_DIAGONAL: bool = False  # 是否叠加三角对角线（False 为纯方格线）
    
    # 拆分镜长文分块：每块最多多少字（按段落/场景切，不在句中切）；
    # 常规一集在此字数内整块一次出，只有超长集才兜底分块
    # 拆分镜每块最多多少字。不是越大越好：输出约为原文的 8 倍 tokens，一块 1500 字约 12000 tokens、要一分多钟；
    # 块之间并行，总耗时约等于最慢的一块，所以块小更快；块大则跨块衔接更好、重复输入更少。
    SHOT_SPLIT_CHUNK_CHARS: int = 1500
    SHOT_SPLIT_CONCURRENCY: int = 3   # 拆分镜同时跑几块（1 = 逐块串行）；供应商限流（429）时调小
    # 转剧本长文分块：每块最多多少字（按段落切，块与块交界同地点同时间的场次会接成一场）
    SCRIPT_CHUNK_CHARS: int = 4000
    # 一键提取资产（一次调用）最多读多少字：有剧本时读剧本全文（剧本比原文短），超过提示分集
    ASSET_EXTRACT_MAX_CHARS: int = 30000

    class Config:
        env_file = ".env"
        case_sensitive = True
    
    @property
    def cors_origins_list(self) -> List[str]:
        """解析CORS origins"""
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",")]


def _apply_desktop(s: Settings) -> Settings:
    """桌面模式：未显式配置的路径/密钥改放应用数据目录。非桌面模式不做任何事。"""
    if not paths.is_desktop():
        return s
    if "STATIC_DIR" not in s.model_fields_set and not os.environ.get("STATIC_DIR"):
        s.STATIC_DIR = str(paths.static_dir_default())
    if not os.environ.get("JWT_SECRET") and "JWT_SECRET" not in s.model_fields_set:
        s.JWT_SECRET = paths.load_or_create_jwt_secret()
    return s


settings = _apply_desktop(Settings())
