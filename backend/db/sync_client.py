"""同步 pymongo 客户端（模型预设、提示词等同步接口共用）

与 motor 异步客户端读同一套配置：MONGODB_URL + MONGODB_DB_NAME。
旧代码曾读 MONGO_URL 并把库名写死为 dongai，导致切换库（如 dongai_e2e）时
这些集合仍落在 dongai。MONGO_URL 仅在未配置 MONGODB_URL 时作为兼容回退。
"""
import os
from functools import lru_cache

from pymongo import MongoClient

from config.settings import settings


def _mongo_url() -> str:
    if "MONGODB_URL" not in os.environ and os.environ.get("MONGO_URL"):
        return os.environ["MONGO_URL"]
    return settings.MONGODB_URL


@lru_cache(maxsize=1)
def get_sync_client() -> MongoClient:
    return MongoClient(_mongo_url())


def get_sync_db():
    """返回当前配置库（settings.MONGODB_DB_NAME）的同步句柄"""
    return get_sync_client()[settings.MONGODB_DB_NAME]
