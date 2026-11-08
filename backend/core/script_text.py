"""剧本场次文本拼接工具。"""
from __future__ import annotations

from typing import List, Dict


def scripts_to_text(scripts: List[Dict]) -> str:
    """把剧本场次拼成连贯文本，供资产提取 / 分镜拆分使用。"""
    blocks = []
    for s in scripts:
        lines = [f"【场次{s.get('scene_no', '')}】"]
        if s.get("location"):
            lines.append(f"地点：{s['location']}")
        if s.get("time"):
            lines.append(f"时间：{s['time']}")
        chars = s.get("characters") or []
        if chars:
            lines.append(f"出场：{', '.join(chars)}")
        if s.get("action"):
            lines.append(f"动作/环境：{s['action']}")
        for d in (s.get("dialogues") or []):
            if isinstance(d, dict):
                lines.append(f"{d.get('speaker', '旁白')}：{d.get('line', '')}")
        if s.get("beat"):
            lines.append(f"节拍：{s['beat']}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def script_scene_blocks(scripts: List[Dict]) -> List[str]:
    """每个场次一段文本（顺序同 scenes），供拆分镜按场次分块：块边界只落在场次之间。"""
    return [scripts_to_text([s]) for s in scripts]


async def load_scripts(db, project_id: str) -> List[Dict]:
    """读项目的剧本场次，按场次号排序；没有剧本返回空列表。"""
    if not project_id:
        return []
    rows = await db.scripts.find({"project_id": project_id}).sort("scene_no", 1).to_list(None)
    return rows or []


async def load_script_text(db, project_id: str):
    """(剧本拼接文本, 场次数)；没有剧本返回 ("", 0)，调用方兜底用小说原文。"""
    rows = await load_scripts(db, project_id)
    if not rows:
        return "", 0
    return scripts_to_text(rows), len(rows)


async def scene_location_of(db, shot: Dict) -> str:
    """分镜所属剧本场次的地点（shot.scene_no → scripts.location）；没有场次返回空串。"""
    no = shot.get("scene_no")
    if no is None or not shot.get("project_id"):
        return ""
    row = await db.scripts.find_one({"project_id": shot["project_id"], "scene_no": no}, {"location": 1})
    return (row or {}).get("location") or ""


def locate_scene_no(lines: List[Dict], scripts: List[Dict]):
    """按台词原文在哪个场次里出现，判断视频段属于第几场；找不到返回 None。

    拆分镜按场次分块，一块可能含多场，模型不回填场次号，这里由代码反查。
    """
    def norm(t: str) -> str:
        return "".join(ch for ch in str(t or "") if ch.isalnum())

    blobs = [(s.get("scene_no"), norm(scripts_to_text([s]))) for s in scripts]
    for ln in lines or []:
        t = norm(ln.get("text") if isinstance(ln, dict) else ln)
        if len(t) < 4:
            continue
        probe = t[:12]
        for no, blob in blobs:
            if probe in blob:
                return no
    return None
