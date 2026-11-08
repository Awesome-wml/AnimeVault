from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from config.settings import settings
from typing import Optional


class MongoDBClient:
    """MongoDB异步客户端"""
    
    client: Optional[AsyncIOMotorClient] = None
    db: Optional[AsyncIOMotorDatabase] = None
    
    @classmethod
    async def connect(cls):
        """连接MongoDB"""
        try:
            cls.client = AsyncIOMotorClient(settings.MONGODB_URL)
            cls.db = cls.client[settings.MONGODB_DB_NAME]
            # 测试连接
            await cls.client.admin.command('ping')
            print(f"✅ MongoDB连接成功: {settings.MONGODB_DB_NAME}")
        except Exception as e:
            print(f"❌ MongoDB连接失败: {str(e)}")
            raise
    
    @classmethod
    async def close(cls):
        """关闭MongoDB连接"""
        if cls.client:
            cls.client.close()
            print("MongoDB连接已关闭")
    
    @classmethod
    def get_db(cls) -> AsyncIOMotorDatabase:
        """获取数据库实例"""
        if cls.db is None:
            raise RuntimeError("数据库未初始化，请先调用connect()")
        return cls.db
    
    @classmethod
    async def create_indexes(cls):
        """创建索引"""
        db = cls.get_db()
        
        # User索引
        await db.users.create_index("username", unique=True)
        
        # Project索引
        await db.projects.create_index("user_id")
        
        # Character索引
        await db.characters.create_index([("user_id", 1), ("project_id", 1)])
        
        # Shot索引
        await db.shots.create_index([("user_id", 1), ("project_id", 1)])
        await db.shots.create_index([("project_id", 1), ("shot_no", 1)])

        # Script索引
        await db.scripts.create_index([("user_id", 1), ("project_id", 1)])
        await db.scripts.create_index([("project_id", 1), ("scene_no", 1)])
        
        print("✅ MongoDB索引创建完成")


# 便捷函数
def get_db() -> AsyncIOMotorDatabase:
    """获取数据库实例"""
    return MongoDBClient.get_db()
