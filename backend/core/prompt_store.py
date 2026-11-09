"""从DB读取默认提示词，fallback到内置常量"""
from db.sync_client import get_sync_db

_db = get_sync_db()

# 通用分类标识：不属于任何特定题材流派的兜底提示词
GENERAL_CATEGORY = "通用"


def get_prompt(type: str, fallback: str = "", category: str = "") -> str:
    """按环节取默认提示词。

    优先级：指定流派(category)的默认提示词 → 通用默认提示词 → 内置常量 fallback。
    """
    if category:
        p = _db.prompts.find_one({"type": type, "category": category, "is_default": True})
        if p and p.get("content"):
            return p["content"]
    p = _db.prompts.find_one({"type": type, "category": GENERAL_CATEGORY, "is_default": True})
    if not p:
        # 兼容旧数据：未打分类的内置提示词也作为通用兜底
        p = _db.prompts.find_one({"type": type, "is_default": True})
    if p and p.get("content"):
        return p["content"]
    return fallback
