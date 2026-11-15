"""资产-分镜绑定与豆包提示词封装。

职责（只回答“这一段用哪些资产、按什么顺序”）：
规则匹配分镜/视频段与项目内角色/场景/道具，生成绑定关系（含类型、身份、引用、图片），
顺序固定为 角色 → 场景 → 道具。

参考图上传顺序与 refN 链接编号不在这里产出：core/video_prompt.py 的 build_upload_plan
拿这里的绑定顺序过滤出实际上传的图，再用同一个列表组装五段式提示词，保证只有一套编号逻辑。
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


def _names(value) -> List[str]:
    """视频段的结构化名字数组（characters / props）；旧数据可能是逗号串。"""
    if isinstance(value, str):
        value = re.split(r"[,，、]", value)
    if not isinstance(value, list):
        return []
    return [str(v).strip() for v in value if v and str(v).strip()]


def collect_bindings(shot: Dict, chars: List[Dict], scenes: List[Dict],
                     props: List[Dict], scene_location: str = "", scene_no=None) -> List[Dict]:
    """规则匹配分镜关联的资产，返回去重后的绑定列表（顺序：角色 → 场景 → 道具）。

    - 视频段有结构化字段 characters / props 时按字段选（代码已校正过名字），否则按名字出现在文本里匹配；
    - 场景：场次地点（剧本场次 location）与视频段 scene 字段作为主背景证据，正文定位词命中作为补充，
      场景全名出现在文本里也算。
    - 角色参考图按段所属场次选形态（core.character_forms.form_for_scene）：scene_nos 命中的形态的图；
      找不到用第一形态并在绑定项 warning 里提示。
    scene_location: 分镜所属场次的地点（剧本场次 location），并入场景归属判断。
    scene_no: 分镜所属场次编号（空则取 shot.scene_no）。

    每个绑定项：
        asset_type: character / scene / prop
        role:       角色 importance（main/support/extra），场景为 scene，道具为 prop
        label:      中文身份标签（主角/配角/路人/场景/道具）
        asset_id:   资产记录 ID（字符串，可能为空）
        name:       资产名
        img:        参考图地址（可能为空）
        form:       角色所用形态名（仅角色）
        warning:    形态不匹配时的提示（仅角色，可能为空）
    """
    from core.character_forms import form_for_scene

    body = " ".join(
        str(shot.get(k) or "") for k in ("text", "prompt", "video_prompt", "scene")
    )
    location = " ".join(x for x in (scene_location or "", str(shot.get("scene") or "")) if x)
    text = " ".join((body, location))
    want_chars = _names(shot.get("characters"))
    want_props = _names(shot.get("props"))
    if scene_no is None:
        scene_no = shot.get("scene_no")
    bindings: List[Dict] = []
    seen = set()

    def _add(asset_type: str, role: str, label: str, asset: Dict, **extra):
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
            "img": extra.pop("img", None) or asset.get("image_path") or asset.get("img_path"),
            **extra,
        })

    for ch in chars:
        name = ch.get("name")
        if name and (name in want_chars if want_chars else name in text):
            importance = ch.get("importance") or ""
            label = _CHARACTER_ROLE_LABEL.get(importance, "角色")
            form, warning = form_for_scene(ch, scene_no)
            _add("character", importance or "character", label, ch,
                 img=form.get("image_path"), form=form.get("name"), warning=warning)

    for sc in _match_scenes(scenes, body, location):
        _add("scene", "scene", _SCENE_LABEL, sc, view=sc.get("view") or sc.get("angle") or "")
    for sc in scenes:
        if sc.get("name") and sc["name"] in text:
            _add("scene", "scene", _SCENE_LABEL, sc, view=sc.get("view") or sc.get("angle") or "")

    for pr in props:
        name = pr.get("name")
        if name and (name in want_props if want_props else name in text):
            _add("prop", "prop", _PROP_LABEL, pr)

    return bindings
