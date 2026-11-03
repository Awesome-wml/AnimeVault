from redis.asyncio import Redis
from config.settings import settings
from typing import Optional
import logging

logger = logging.getLogger(__name__)


class RedisClient:
    """Redis异步客户端（可选组件）"""
    
    client: Optional[Redis] = None
    enabled: bool = False
    
    @classmethod
    async def connect(cls):
        """连接Redis，失败不阻断程序启动"""
        try:
            cls.client = Redis.from_url(
                settings.REDIS_URL,
                encoding="utf-8",
                decode_responses=True
            )
            # 测试连接
            await cls.client.ping()
            cls.enabled = True
            print(f"✅ Redis连接成功: {settings.REDIS_URL}")
        except Exception as e:
            cls.enabled = False
            cls.client = None
            logger.warning(f"⚠️  Redis连接失败（可选组件）: {str(e)}")
            print(f"⚠️  Redis未启用，程序将继续运行（Redis为可选组件）")
    
    @classmethod
    async def close(cls):
        """关闭Redis连接"""
        if cls.client:
            await cls.client.close()
            print("Redis连接已关闭")
    
    @classmethod
    def get_client(cls) -> Optional[Redis]:
        """获取Redis客户端"""
        if not cls.enabled:
            logger.debug("Redis未启用，返回None")
            return None
        return cls.client
    
    @classmethod
    async def set(cls, key: str, value: str, ex: int = None):
        """设置键值"""
        if cls.enabled and cls.client:
            await cls.client.set(key, value, ex=ex)
    
    @classmethod
    async def get(cls, key: str) -> Optional[str]:
        """获取值"""
        if cls.enabled and cls.client:
            return await cls.client.get(key)
        return None
    
    @classmethod
    async def delete(cls, key: str):
        """删除键"""
        if cls.enabled and cls.client:
            await cls.client.delete(key)


# 便捷函数
def get_redis() -> Optional[Redis]:
    """获取Redis客户端"""
    return RedisClient.get_client()
