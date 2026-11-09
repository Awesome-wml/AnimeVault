"""内置提示词表与启动同步

内置提示词的正文只在 core/prompt_tpl.py 维护（这里只引用常量，不写正文）。
启动时 sync_builtin_prompts(db) 把它们同步进 Mongo 的 prompts 集合，每个 type 恰好一条
is_builtin=True、category=通用 的记录，用户在设置页能看到、能改、能复制、能恢复。

记录字段：
- content        当前生效的内置内容（用户可改）
- builtin_hash   content 最近一次由代码写入时，代码常量的 sha256；用来判断用户有没有改过
- has_update     用户改过而且代码之后又更新了 → True（页面提示“代码已有新版本”）
- latest_builtin has_update 时保存的最新代码内容，供“恢复内置”

同步规则：
- 库里没有 → 插入。
- 库里内容未被用户改过（sha256(content) 等于 builtin_hash，或等于当前代码 hash，或旧占位没有 hash）→ 覆盖成代码内容。
- 用户改过 → 保留用户内容；代码与上次写入不同时标 has_update=True 并存 latest_builtin。
- is_builtin=True 但 type 不在表里的旧占位（如 video）→ 删除；同 type 多条内置只留最早一条。
- 非内置记录一律不动。
"""
import hashlib
from datetime import datetime

from core import prompt_tpl as T

GENERAL_CATEGORY = "通用"

# type 与 frontend/src/views/settings/prompt-types.js 对齐；video 已废弃（视频提示词由代码按分镜组装）
BUILTIN_PROMPTS = [
    {
        "type": "novel", "name": "内置·生成小说", "content": T.NOVEL_GENERATE_PROMPT,
        "description": "小说页「AI 写小说」。占位符：{genre} 题材、{style} 风格、{protagonist} 主角、{outline} 大纲、"
                       "{target_words} 目标字数、{genre_rhythm} 题材节奏。",
    },
    {
        "type": "novel_polish", "name": "内置·小说润色", "content": T.NOVEL_POLISH_PROMPT,
        "description": "小说页「润色」，把原文改成适合拆分镜、配音的漫剧文本。占位符：{novel_text} 原文、"
                       "{person_rule} 人称要求、{genre_rhythm} 题材节奏。",
    },
    {
        "type": "script_convert", "name": "内置·剧本转换", "content": T.SCRIPT_CONVERT_PROMPT,
        "description": "剧本页「转剧本」，小说转分场剧本。占位符：{novel_paragraph} 小说段落、{style_block} 作品风格、"
                       "{genre_rhythm} 题材节奏、{person_rule} 人称要求、{length_rule} 篇幅要求、{chunk_note} 分块说明。",
    },
    {
        "type": "character_extract", "name": "内置·角色提取", "content": T.CHARACTER_EXTRACT_PROMPT,
        "description": "角色页「AI 提取角色」。占位符：{novel_text} 文本、{style_block} 作品风格。",
    },
    {
        "type": "prop_extract", "name": "内置·道具提取", "content": T.PROP_EXTRACT_PROMPT,
        "description": "道具页「AI 提取道具」。占位符：{novel_text} 文本、{style_block} 作品风格。",
    },
    {
        "type": "scene_extract", "name": "内置·场景提取", "content": T.SCENE_EXTRACT_PROMPT,
        "description": "场景页「AI 提取场景」。占位符：{novel_text} 文本、{style_block} 作品风格。",
    },
    {
        "type": "asset_extract", "name": "内置·资产提取（三合一）", "content": T.ASSET_EXTRACT_PROMPT,
        "description": "小说页「一键提取」，一次提取角色、道具、场景。占位符：{novel_text} 文本（有剧本时为剧本）、"
                       "{style_block} 作品风格。",
    },
    {
        "type": "character_sheet", "name": "内置·角色三视图", "content": T.CHARACTER_SHEET_PROMPT,
        "description": "角色参考图（三视图）的文生图提示词。占位符：{character_name} 角色名、{character_description} 角色描述、"
                       "{gender} 性别、{age_group} 年龄段、{art_style} 画风。",
    },
    {
        "type": "prop_ref", "name": "内置·道具参考图", "content": T.PROP_REF_PROMPT,
        "description": "道具参考图的文生图提示词。占位符：{prop_name} 道具名、{prop_type} 道具类型、"
                       "{prop_description} 道具描述、{art_style} 画风。",
    },
    {
        "type": "scene_ref", "name": "内置·场景参考图", "content": T.SCENE_REF_PROMPT,
        "description": "无人场景参考图的文生图提示词。占位符：{scene_name} 场景名、{scene_type} 场景类型、"
                       "{scene_description} 场景描述、{art_style} 画风。",
    },
    {
        "type": "split_shots", "name": "内置·拆分镜（小说）", "content": T.SHOT_SPLIT_PROMPT,
        "description": "分镜页「拆分镜」，作品没有剧本时按小说段落拆。占位符：{novel_paragraph} 文本、{asset_block} 资产清单、"
                       "{style_block} 作品风格、{genre_rhythm} 题材节奏、{model_name} 视频模型、{segment_seconds} 每段秒数、"
                       "{segment_count_hint} 段数提示、{novel_seconds} 朗读时长、{chars_low}/{chars_high} 每段字数区间、"
                       "{content_low}/{content_high} 内容量区间、{chunk_note} 分块说明。",
    },
    {
        "type": "split_shots_script", "name": "内置·拆分镜（剧本）", "content": T.SHOT_SPLIT_SCRIPT_PROMPT,
        "description": "分镜页「拆分镜」，作品已有剧本时按场次拆。占位符与「拆分镜（小说）」相同，{novel_paragraph} 为剧本场次。",
    },
    {
        "type": "prompt_optimize", "name": "内置·文生图提示词优化", "content": T.PROMPT_OPTIMIZE,
        "description": "把画面描述改写成结构化文生图提示词（预留环节，当前流程未接入）。占位符：{original_prompt} 原始描述、"
                       "{image_model} 文生图模型、{art_style} 画风。",
    },
]

BUILTIN_TYPES = [p["type"] for p in BUILTIN_PROMPTS]
_BY_TYPE = {p["type"]: p for p in BUILTIN_PROMPTS}


def content_hash(content: str) -> str:
    return hashlib.sha256((content or "").encode("utf-8")).hexdigest()


def builtin_for(type: str):
    """某 type 的内置定义（含 content），不存在返回 None"""
    return _BY_TYPE.get(type)


def builtin_state(type: str, content: str, builtin_hash: str, from_code: bool = True) -> dict:
    """根据当前内容算内置记录的状态字段。

    - 内容等于当前代码 → 跟代码一致：builtin_hash 更新为当前代码 hash，has_update=False。
    - from_code（启动同步）且内容等于 builtin_hash 对应的旧代码或旧占位没有 hash → 用户没改：覆盖成当前代码。
    - 内容是用户改过的 → 保留；代码自上次写入后变了（builtin_hash != 当前）→ has_update=True，存 latest_builtin。
    用户在页面保存时传 from_code=False：只要与当前代码不同就按用户内容处理。
    返回 {"set": {...}, "unset": [...]}。
    """
    bp = _BY_TYPE[type]
    code = bp["content"]
    code_hash = content_hash(code)
    cur_hash = content_hash(content)
    unmodified = cur_hash == code_hash or (from_code and (not builtin_hash or cur_hash == builtin_hash))
    if unmodified:
        return {"set": {"content": code, "builtin_hash": code_hash, "has_update": False},
                "unset": ["latest_builtin"]}
    if builtin_hash != code_hash:
        return {"set": {"has_update": True, "latest_builtin": code}, "unset": []}
    return {"set": {"has_update": False}, "unset": ["latest_builtin"]}


def sync_builtin_prompts(db) -> dict:
    """把内置提示词同步进 db.prompts，幂等。返回统计 {inserted, updated, kept, removed}。"""
    stats = {"inserted": 0, "updated": 0, "kept": 0, "removed": 0}
    now = datetime.now()

    # 1) 清掉 type 不在新表里的旧内置占位（如 video）
    r = db.prompts.delete_many({"is_builtin": True, "type": {"$nin": BUILTIN_TYPES}})
    stats["removed"] += r.deleted_count

    for bp in BUILTIN_PROMPTS:
        rows = list(db.prompts.find({"type": bp["type"], "is_builtin": True}).sort("created_at", 1))
        meta = {"name": bp["name"], "description": bp["description"], "category": GENERAL_CATEGORY,
                "is_builtin": True, "is_default": False, "version": "内置"}
        if not rows:
            db.prompts.insert_one({**meta, "type": bp["type"], "content": bp["content"],
                                   "builtin_hash": content_hash(bp["content"]), "has_update": False,
                                   "created_at": now, "updated_at": now})
            stats["inserted"] += 1
            continue
        # 同 type 多条内置只留最早一条
        extra_ids = [row["_id"] for row in rows[1:]]
        if extra_ids:
            db.prompts.delete_many({"_id": {"$in": extra_ids}})
            stats["removed"] += len(extra_ids)
        row = rows[0]
        state = builtin_state(bp["type"], row.get("content") or "", row.get("builtin_hash") or "")
        changed = any(row.get(k) != v for k, v in state["set"].items()) or \
            any(k in row for k in state["unset"]) or any(row.get(k) != v for k, v in meta.items())
        update = {"$set": {**meta, **state["set"], "updated_at": now}}
        if state["unset"]:
            update["$unset"] = {k: "" for k in state["unset"]}
        db.prompts.update_one({"_id": row["_id"]}, update)
        stats["updated" if changed else "kept"] += 1
    return stats
