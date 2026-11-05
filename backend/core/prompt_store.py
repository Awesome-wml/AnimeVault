"""从DB读取默认提示词，fallback到内置常量"""
from pymongo import MongoClient
import os

_client = MongoClient(os.environ.get("MONGO_URL", "mongodb://admin:dongai_mongo_2024@localhost:27017/"))
_db = _client.dongai

def get_prompt(type: str, fallback: str = "") -> str:
    p = _db.prompts.find_one({"type": type, "is_default": True})
    if p and p.get("content"):
        return p["content"]
    return fallback
