from pydantic_settings import BaseSettings
from typing import List


class Settings(BaseSettings):
    """全局配置"""
    
    # MongoDB配置
    MONGODB_URL: str = "mongodb://admin:dongai_mongo_2024@localhost:27017/"
    MONGODB_DB_NAME: str = "dongai"
    
    # Redis配置（可选）
    REDIS_URL: str = "redis://localhost:6379/0"
    
    # 静态文件目录
    STATIC_DIR: str = "../static"
    
    # JWT配置
    JWT_SECRET: str = "your-secret-key-please-change-this"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 43200  # 30天
    
    # CORS配置
    CORS_ORIGINS: str = "http://localhost:8080,http://localhost:3000"

    # 剪映草稿目录（默认macOS路径，可用环境变量覆盖）
    JIANYING_DRAFT_DIR: str = ""  # 空则自动检测
    # 剪映草稿模板目录（含 draft_info.json / draft_meta_info.json），空则用 backend/.jianying_template
    JIANYING_TEMPLATE_DIR: str = ""

    # 角色设定板脸部/皮肤线框网格后处理（弱化真人肖像识别度，零第三方依赖）
    FACE_GRID_ENABLED: bool = True
    FACE_GRID_CELL: int = 22       # 网格单元边长（像素），越小越密
    FACE_GRID_ALPHA: int = 70      # 网格不透明度 0-255
    FACE_GRID_DIAGONAL: bool = False  # 是否叠加三角对角线（False 为纯方格线）
    
    # 拆分镜长文分块：每块最多多少字（按段落/场景切，不在句中切）
    SHOT_SPLIT_CHUNK_CHARS: int = 1500

    class Config:
        env_file = ".env"
        case_sensitive = True
    
    @property
    def cors_origins_list(self) -> List[str]:
        """解析CORS origins"""
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",")]


settings = Settings()
