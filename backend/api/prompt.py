"""提示词管理 API（只读）

提示词以 core/prompts/system.json（骨架+契约）与 constraints.json（约束+题材变体）为准，运行时由
core/prompt_registry 读取，不再读写 Mongo prompts 集合。这里只把注册表展开成列表给设置页展示；
要改提示词请改这两个 JSON 文件（走代码评审与发版）。
"""
from fastapi import APIRouter, Depends

from api.auth import get_current_user
from core import prompt_registry as R
from core.style_library import GENRES

router = APIRouter(prefix="/api/prompts", tags=["prompts"], dependencies=[Depends(get_current_user)])

GENERAL_CATEGORY = "通用"
SOURCE_NOTE = "提示词在 core/prompts/ 文件（system.json、constraints.json）里维护"

# 页面展示用的环节名（缺省用 key）
_NAMES = {
    "novel": "生成小说", "novel_polish": "小说润色", "script_convert": "剧本转换",
    "character_extract": "角色提取", "prop_extract": "道具提取", "scene_extract": "场景提取",
    "asset_extract": "资产提取（三合一）", "character_sheet": "角色三视图", "prop_ref": "道具参考图",
    "scene_ref": "场景参考图", "storyboard": "分镜四格图", "split_shots": "拆分镜（小说）",
    "split_shots_script": "拆分镜（剧本）", "prompt_optimize": "文生图提示词优化",
    "shot_plan": "拆分镜 · 全集规划", "shot_review": "拆分镜 · 审片", "voice_design": "音色设计",
}

CATEGORIES = list(dict.fromkeys([GENERAL_CATEGORY] + [g["genre"] for g in GENRES] + ["韩剧"]))


def _variant_text(v) -> str:
    return (v.get("text", "") if isinstance(v, dict) else v) or ""


def _rows() -> list:
    sys_doc = R._load(R._SYSTEM_FILE).get("prompts", {})
    con_doc = R._load(R._CONSTRAINT_FILE).get("prompts", {})
    rows = []
    for key, s in sys_doc.items():
        c = con_doc.get(key, {}) or {}
        name = _NAMES.get(key, key)
        base = {"type": key, "kind": s.get("kind", "text"), "is_builtin": True, "is_default": False,
                "has_update": False, "read_only": True, "version": "注册表"}
        rows.append({**base, "_id": key, "name": f"{name}", "category": GENERAL_CATEGORY,
                     "content": c.get("default", "") or "", "system": s.get("system", "") or "",
                     "contract": s.get("contract", "") or ""})
        for genre, v in (c.get("variants") or {}).items():
            rows.append({**base, "_id": f"{key}:{genre}", "name": f"{name}·{genre}", "category": genre,
                         "content": _variant_text(v), "system": "", "contract": "",
                         "replace": bool(isinstance(v, dict) and v.get("replace"))})
    return rows


@router.get("")
def list_prompts(type: str = "", category: str = ""):
    rows = [r for r in _rows() if (not type or r["type"] == type) and (not category or r["category"] == category)]
    return {"data": rows, "categories": CATEGORIES, "read_only": True, "note": SOURCE_NOTE}
