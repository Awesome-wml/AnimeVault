"""资产-分镜绑定与豆包提示词封装。

职责：
1. 规则匹配分镜文本与项目内角色/场景/道具，生成绑定关系（含类型、身份、引用、图片）。
2. 按绑定顺序封装送给豆包的视频提示词：图片清单 + @资产 + 画面描述。
3. 按绑定顺序收集参考图文件路径，保证提示词编号与实际上传顺序一致。
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Dict, Optional


# 角色重要性 → 中文身份标签
_CHARACTER_ROLE_LABEL = {
    "main": "主角",
    "support": "配角",
    "extra": "路人",
}
# 场景/道具身份标签
_SCENE_LABEL = "场景"
_PROP_LABEL = "道具"


def collect_bindings(shot: Dict, chars: List[Dict], scenes: List[Dict], props: List[Dict]) -> List[Dict]:
    """规则匹配分镜关联的资产，返回去重后的绑定列表（顺序：角色 → 场景 → 道具）。

    每个绑定项：
        asset_type: character / scene / prop
        role:       角色 importance（main/support/extra），场景为 scene，道具为 prop
        label:      中文身份标签（主角/配角/路人/场景/道具）
        asset_id:   资产记录 ID（字符串，可能为空）
        name:       资产名
        img:        参考图地址（可能为空）
    """
    text = " ".join(
        (shot.get("text", "") or "", shot.get("prompt", "") or "", shot.get("video_prompt", "") or "")
    )
    bindings: List[Dict] = []
    seen = set()

    def _add(asset_type: str, role: str, label: str, asset: Dict):
        name = asset.get("name")
        if not name:
            return
        key = (asset_type, name)
        if key in seen:
            return
        seen.add(key)
        asset_id = asset.get("_id")
        bindings.append({
            "asset_type": asset_type,
            "role": role,
            "label": label,
            "asset_id": str(asset_id) if asset_id else None,
            "name": name,
            "img": asset.get("image_path") or asset.get("img_path"),
        })

    for ch in chars:
        if ch.get("name") and ch["name"] in text:
            importance = ch.get("importance") or ""
            label = _CHARACTER_ROLE_LABEL.get(importance, "角色")
            _add("character", importance or "character", label, ch)

    for sc in scenes:
        if sc.get("name") and sc["name"] in text:
            _add("scene", "scene", _SCENE_LABEL, sc)

    for pr in props:
        if pr.get("name") and pr["name"] in text:
            _add("prop", "prop", _PROP_LABEL, pr)

    return bindings


def _inline_image_refs(text: str, bindings: List[Dict]) -> str:
    """在画面正文里，资产名出现的位置内联标注对应图片编号，如 车钥匙【@图片4】。"""
    if not text:
        return text
    # 名字长的先替换，避免短名误伤长名子串
    ordered = sorted(
        enumerate(bindings),
        key=lambda x: len(x[1].get("name", "") or ""),
        reverse=True,
    )
    for idx, b in ordered:
        name = (b.get("name") or "").strip()
        if not name:
            continue
        marker = f"【@图片{idx + 1}】"
        if marker in text:
            continue
        text = text.replace(name, f"{name}{marker}")
    return text


def _fmt_duration(v) -> str:
    try:
        d = float(v)
        return str(int(d)) if d == int(d) else str(round(d, 1))
    except (TypeError, ValueError):
        return "15"


def build_video_prompt(shot: Dict, bindings: List[Dict]) -> str:
    """按绑定顺序封装豆包视频提示词。

    结构：硬性参数头 → 参考素材清单 → 画面正文（内联【@图片n】）→ 硬性禁区 → 收尾指令。
    """
    base_prompt = shot.get("prompt") or shot.get("video_prompt") or ""
    dur = _fmt_duration(shot.get("duration") or 15)
    try:
        seg = f"SEG{int(shot.get('shot_no') or 1):03d}"
    except (TypeError, ValueError):
        seg = f"SEG{shot.get('shot_no') or 1}"

    header = (f"生成视频：【硬性参数】生成{seg}，严格生成长度为{dur}秒，"
              "16:9横屏，无水印、无平台标识、无角标、无logo。")
    footer = (f"【硬性禁区】1.严格生成长度为{dur}秒，禁止任何时长压缩。"
              "2.无水印、无平台标识、无角标。3.不生成随机字幕。"
              "4.角色五官服装保持一致，不换脸、手部不畸形。"
              "5.光影环境保持统一。6.禁止提前出现未出场角色。")
    closing = "不要确认，不要反问，直接生成视频。"

    if not bindings:
        return "\n\n".join([p for p in [header, base_prompt, footer, closing] if p])

    lines = ["参考素材："]
    for idx, b in enumerate(bindings, start=1):
        lines.append(f"图{idx}: {b['name']}（{b['label']}）")

    body = _inline_image_refs(base_prompt, bindings)
    parts = [header, "\n".join(lines)]
    if body:
        parts.append(body)
    parts.append(footer)
    parts.append(closing)
    return "\n\n".join(parts)


def binding_image_files(bindings: List[Dict], static_dir: Path) -> List[str]:
    """按绑定顺序收集存在的参考图绝对路径，供自动化按序上传。"""
    files: List[str] = []
    for b in bindings:
        img = b.get("img")
        if not img:
            continue
        full = static_dir / img
        if full.exists() and str(full) not in files:
            files.append(str(full))
    return files
