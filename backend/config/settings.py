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
    
    class Config:
        env_file = ".env"
        case_sensitive = True
    
    @property
    def cors_origins_list(self) -> List[str]:
        """解析CORS origins"""
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",")]


settings = Settings()
