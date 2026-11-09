"""按环节取提示词：用户默认 → 内置记录 → 代码常量"""
from db.sync_client import get_sync_db

_db = get_sync_db()

# 通用分类标识：不属于任何特定题材流派的兜底提示词
GENERAL_CATEGORY = "通用"


def _user_default(db, type: str, category_query) -> str:
    """用户自己设的默认（非内置）"""
    p = db.prompts.find_one({"type": type, "is_default": True, "is_builtin": {"$ne": True}, "category": category_query})
    return p["content"] if p and p.get("content") else ""


def get_prompt(type: str, fallback: str = "", category: str = "", db=None, alias_types=()) -> str:
    """按环节取提示词。

    优先级：该题材(category)的用户默认 → 通用的用户默认 → 内置记录（库里 is_builtin，用户可改）→ 代码常量 fallback。
    prompt_id 指定的那一层在 core.llm_factory.resolve_prompt 里。
    alias_types：用户默认那两层额外兼容的旧 type（如剧本版拆分镜 split_shots_script 也认 split_shots 的用户默认）。
    """
    db = db if db is not None else _db
    types = (type, *alias_types)
    if category and category != GENERAL_CATEGORY:
        for t in types:
            c = _user_default(db, t, category)
            if c:
                return c
    # 兼容旧数据：没打分类的记录也算通用
    for t in types:
        c = _user_default(db, t, {"$in": [GENERAL_CATEGORY, None, ""]})
        if c:
            return c
    p = db.prompts.find_one({"type": type, "is_builtin": True})
    if p and p.get("content"):
        return p["content"]
    return fallback
