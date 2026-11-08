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
