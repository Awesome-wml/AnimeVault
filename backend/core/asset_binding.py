"""资产-分镜绑定与豆包提示词封装。

职责：
1. 规则匹配分镜文本与项目内角色/场景/道具，生成绑定关系（含类型、身份、引用、图片）。
2. 按绑定顺序封装送给豆包的视频提示词：图片清单 + @资产 + 画面描述。
3. 按绑定顺序收集参考图文件路径，保证提示词编号与实际上传顺序一致。
"""
from __future__ import annotations

import re
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

# 通用场景定位名词：出现在场景名/描述与分镜文本中时，作为场景归属证据。
# 仅维护可定位的地点/空间名词，不含任何具体作品元素，可跨小说复用。
_SCENE_LOCATION_WORDS = [
    "包厢", "包间", "会所", "酒店", "餐厅", "酒吧", "茶馆", "咖啡厅",
    "街道", "街口", "路口", "斑马线", "天桥", "停车场", "车库", "巷子", "胡同",
    "客厅", "卧室", "书房", "办公室", "会议室", "走廊", "楼梯", "大堂", "走廊",
    "天台", "屋顶", "操场", "学校", "医院", "商场", "超市", "市场", "码头",
    "港口", "车站", "机场", "公园", "广场", "河边", "湖边", "海边", "山顶",
    "森林", "田野", "公路", "高速", "桥", "隧道", "庭院", "宴会厅", "酒会",
    "晚宴", "舞台", "影院", "展厅", "画廊", "健身房", "泳池", "球场", "宿舍",
]


def _scene_evidence_words(scene: Dict) -> List[str]:
    """从场景名与描述中抽取可定位的空间名词（去重、保序）。"""
    blob = " ".join((scene.get("name", "") or "", scene.get("description", "") or ""))
    words: List[str] = []
    for w in _SCENE_LOCATION_WORDS:
        if w in blob and w not in words:
            words.append(w)
    return words


# 对比/反差类从句：其中出现的场景词属于修辞对照，不计入正文场景命中。
_RHETORIC_PATTERNS = [
    r"[与跟和同][^，。；,!！?？]*?(?:反差|对比|呼应|不同|不像|相较|区别)",
]


def _strip_rhetoric(text: str) -> str:
    """剔除对比/反差类从句，避免修辞语境里的场景词被误判为当前场景。"""
    for pattern in _RHETORIC_PATTERNS:
        text = re.sub(pattern, "", text)
    return text


def _scene_loc_hit(scene: Dict, location: str) -> bool:
    """场次地点是否指向该场景（全名或定位词命中）。"""
    name = scene.get("name") or ""
    if name and name in location:
        return True
    return any(w in location for w in _scene_evidence_words(scene))


def _scene_body_hits(scene: Dict, body: str) -> int:
    """正文（剔除修辞后）命中的定位词数量。"""
    return sum(1 for w in _scene_evidence_words(scene) if w in body)


def _match_scenes(scenes: List[Dict], body: str, location: str = "") -> List[Dict]:
    """选出应绑定的场景：场次地点兜底主背景，正文命中作为补充。

    - 主背景：location 指向的场景（可能为空）；
    - 补充场景：正文剔除修辞后，定位词命中且为唯一最高分者；并列则不补；
    - 合并去重，主背景在前。
    """
    body_clean = _strip_rhetoric(body)

    main_scenes = [sc for sc in scenes if _scene_loc_hit(sc, location)]

    scored = [(_scene_body_hits(sc, body_clean), sc) for sc in scenes]
    scored = [(n, sc) for n, sc in scored if n > 0]
    extra: List[Dict] = []
    if scored:
        scored.sort(key=lambda x: x[0], reverse=True)
        top = scored[0][0]
        winners = [sc for n, sc in scored if n == top]
        if len(winners) == 1:
            extra = winners

    ordered = list(main_scenes)
    for sc in extra:
        if sc not in ordered:
            ordered.append(sc)
    return ordered


def collect_bindings(shot: Dict, chars: List[Dict], scenes: List[Dict],
                     props: List[Dict], scene_location: str = "") -> List[Dict]:
    """规则匹配分镜关联的资产，返回去重后的绑定列表（顺序：角色 → 场景 → 道具）。

    每个绑定项：
        asset_type: character / scene / prop
        role:       角色 importance（main/support/extra），场景为 scene，道具为 prop
        label:      中文身份标签（主角/配角/路人/场景/道具）
        asset_id:   资产记录 ID（字符串，可能为空）
        name:       资产名
        img:        参考图地址（可能为空）

    scene_location: 分镜所属场次的地点（剧本场次 location），并入场景归属判断。
    """
    body = " ".join(
        (shot.get("text", "") or "", shot.get("prompt", "") or "",
         shot.get("video_prompt", "") or "")
    )
    location = scene_location or ""
    text = " ".join((body, location))
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

    for sc in _match_scenes(scenes, body, location):
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

    结构：硬性参数头 → 参考素材清单 → 画面正文（内联【@图片n】）→ 台词与旁白（AI 原文透传）→ 硬性禁区 → 收尾指令。
    后端只加硬参数、资产绑定与段标题，不解析、不重排、不重写 AI 产出的画面与对白。
    """
    base_prompt = shot.get("prompt") or shot.get("video_prompt") or ""
    dialogue = shot.get("text") or ""
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

    body_parts: List[str] = []
    if base_prompt:
        body_parts.append("【画面】" + _inline_image_refs(base_prompt, bindings))
    if dialogue:
        body_parts.append("【台词与旁白】\n" + _inline_image_refs(dialogue, bindings))
    body = "\n\n".join(body_parts)

    if not bindings:
        return "\n\n".join([p for p in [header, body, footer, closing] if p])

    lines = ["参考素材："]
    for idx, b in enumerate(bindings, start=1):
        lines.append(f"图{idx}: {b['name']}（{b['label']}）")

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
