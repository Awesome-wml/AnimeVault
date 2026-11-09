"""四格分镜图：每个视频段一张 2×2 四格图（左上 S1 → 右上 S2 → 左下 S3 → 右下 S4），代替单张首帧作视频参考图。

四格由代码从段内小镜头（beats）挑出，模型不另出：
- 恰好 4 个小镜头：一格一个；
- 不足 4 个：每个小镜头至少占一格，多出来的格按时长比例分给长的小镜头（同一镜头稍后的瞬间）；
- 多于 4 个：首个 + 两个情绪高点（有表情、有台词、景别紧的优先）+ 尾态。

对外三个口径：
- storyboard_panels(seg)：四格清单 [{panel, pos, beat_index, start, end, text}]，前端展示、视频提示词标注共用；
- storyboard_body(seg, genre)：段级“整体设定 + 四格内容”文字（存到 segment.storyboard_prompt，可手改）；
- storyboard_prompt(body, chars, art_style, scene_no)：出图时把人物外观、画风填进 STORYBOARD_PROMPT 模板。

提示词直接发给文生图模型，不能带“裸露/血腥”一类敏感词（否定句也会被拦），见 test_image_prompt_safety.py。
"""
import re
from typing import Dict, List, Optional

from core.genre_rhythm import lighting_for_mood
from core.llm_factory import safe_format
from core.prompt_tpl import STORYBOARD_PROMPT

PANELS = 4
PANEL_POS = ("左上", "右上", "左下", "右下")
PANEL_IDS = tuple(f"S{i}" for i in range(1, PANELS + 1))
NO_EXPRESSION = ("", "无", "无表情")
TIGHT_SIZES = ("特写", "近景", "中近景")
MAX_FACE_CHARS = 80      # 人物外观里面部描述最多取这么多字（四格图是场景图，不是三视图）
MAX_OUTFIT_CHARS = 80


def _fmt(x) -> str:
    try:
        f = round(float(x), 1)
    except (TypeError, ValueError):
        return "0"
    return str(int(f)) if f.is_integer() else f"{f:g}"


def _beat_duration(b: dict) -> float:
    try:
        return max(float(b.get("end") or 0) - float(b.get("start") or 0), 0.0)
    except (TypeError, ValueError):
        return 0.0


def _expression(b: dict) -> str:
    return str(b.get("expression") or "").strip().rstrip("，,。；;")


def _emotion_score(b: dict) -> int:
    """情绪高点打分：有表情 +2，说了台词 +1，特写/近景/中近景 +1。"""
    score = 0
    if _expression(b) not in NO_EXPRESSION:
        score += 2
    if b.get("line_refs"):
        score += 1
    if any(s in str(b.get("shot_size") or "") for s in TIGHT_SIZES):
        score += 1
    return score


def pick_beats(beats: List[dict]) -> List[int]:
    """四格各取第几个小镜头（下标，按时间顺序，可重复）。没有小镜头返回空列表。"""
    n = len(beats)
    if n == 0:
        return []
    if n == PANELS:
        return list(range(n))
    if n < PANELS:
        counts = [1] * n
        durations = [_beat_duration(b) for b in beats]
        for _ in range(PANELS - n):
            # 多出来的格给“每格摊到的时长”最大的小镜头；时长都为 0 时给最后一个
            shares = [durations[i] / counts[i] for i in range(n)]
            best = max(range(n), key=lambda i: (shares[i], i))
            counts[best] += 1
        return [i for i in range(n) for _ in range(counts[i])]
    middle = list(range(1, n - 1))
    middle.sort(key=lambda i: (-_emotion_score(beats[i]), i))
    highs = sorted(middle[: PANELS - 2])
    return [0] + highs + [n - 1]


def _people_in(action: str, names: List[str]) -> List[str]:
    return [nm for nm in names if nm and nm in action]


def storyboard_panels(seg: dict) -> List[Dict]:
    """四格清单：每格 = 格号、方位、对应小镜头下标、起止秒、一句画面描述（景别、人物与站位、动作、表情、关键道具）。

    同一小镜头占多格时，后面的格写成“同一镜头稍后的瞬间”，起止秒按格数把该镜头的时间均分。
    """
    beats = [b for b in (seg.get("beats") or []) if isinstance(b, dict)]
    picks = pick_beats(beats)
    names = [str(x) for x in (seg.get("characters") or []) if x]
    props = [str(x) for x in (seg.get("props") or []) if x]
    out: List[Dict] = []
    for k, bi in enumerate(picks):
        b = beats[bi]
        repeat_total = picks.count(bi)
        repeat_no = picks[: k + 1].count(bi)  # 本镜头的第几格（1 起）
        start, end = float(b.get("start") or 0), float(b.get("end") or 0)
        if repeat_total > 1:
            step = (end - start) / repeat_total
            start, end = start + step * (repeat_no - 1), start + step * repeat_no
        action = str(b.get("action") or "").strip().rstrip("，,。；;")
        expr = _expression(b)
        who = _people_in(action, names) or names
        bits = []
        shot = "，".join(x for x in (b.get("shot_size"), b.get("camera"), b.get("move")) if x)
        bits.append(shot or "中近景")
        if who:
            bits.append("人物：" + "、".join(who))
        else:
            bits.append("无人物，环境空镜")
        if action:
            bits.append(("同一镜头稍后的瞬间，动作延续：" if repeat_no > 1 else "动作：") + action)
        if expr not in NO_EXPRESSION:
            bits.append(f"表情：{expr}")
        used_props = [p for p in props if p in action] or props
        if used_props:
            bits.append("关键道具：" + "、".join(used_props))
        out.append({
            "panel": PANEL_IDS[k], "pos": PANEL_POS[k], "beat_index": bi,
            "start": round(start, 1), "end": round(end, 1), "text": "；".join(bits),
        })
    return out


def panel_tags(seg: dict) -> List[str]:
    """每个小镜头在四格图里对应的格（给【画面】时间段前的标注）：
    “S1 左上格”、占两格的“S2–S3 右上、左下格”、没选中的“S2 之后的过渡”。"""
    beats = seg.get("beats") or []
    by_beat: Dict[int, List[int]] = {}
    for k, p in enumerate(storyboard_panels(seg)):
        by_beat.setdefault(p["beat_index"], []).append(k)
    tags, last = [], None
    for bi in range(len(beats)):
        ks = by_beat.get(bi)
        if ks:
            ids = PANEL_IDS[ks[0]] if len(ks) == 1 else f"{PANEL_IDS[ks[0]]}–{PANEL_IDS[ks[-1]]}"
            tags.append(f"{ids} {'、'.join(PANEL_POS[k] for k in ks)}格")
            last = PANEL_IDS[ks[-1]]
        else:
            tags.append(f"{last or PANEL_IDS[0]} 之后的过渡")
    return tags


def storyboard_setting(seg: dict, genre: str = "") -> str:
    """整体设定：场景（含时辰）+ 站位 + 光影（按 mood 映射，与视频提示词同一张表）+ 情绪基调。"""
    scene = str(seg.get("scene") or "").strip().rstrip("；;。")
    positions = str(seg.get("positions") or "").strip().rstrip("；;。")
    mood = str(seg.get("mood") or "").strip().rstrip("；;。")
    bits = []
    if scene:
        bits.append(f"场景：{scene}")
    if positions:
        bits.append(f"站位：{positions}")
    bits.append(f"光影：{lighting_for_mood(mood, genre)}")
    if mood:
        bits.append(f"情绪基调：{mood}")
    return "；".join(bits)


def storyboard_body(seg: dict, genre: str = "") -> str:
    """段级四格文案（存到 segment.storyboard_prompt）：整体设定 + 四格各一行。没有小镜头时返回空串。"""
    panels = storyboard_panels(seg)
    if not panels:
        return ""
    lines = [f"【整体设定】{storyboard_setting(seg, genre)}", "【四格内容】"]
    for p in panels:
        lines.append(f"第{'一二三四'[int(p['panel'][1:]) - 1]}格（{p['pos']}）：{p['text']}")
    return "\n".join(lines)


_NUMBERED = re.compile(r"[①②③④⑤]")


def _face_and_outfit(char: dict, form: dict) -> tuple:
    """面部与穿搭两段文字。新数据直接取 face / 形态 outfit；旧数据只有 description（①基本 ②面部 ③体态 ④穿搭 ⑤特质）
    时取 ② 作面部、④ 作穿搭，没有编号就整段截断。"""
    from core.character_forms import character_face

    face = (char.get("face") or "").strip()
    outfit = str(form.get("outfit") or "").strip()
    desc = (char.get("description") or "").strip()
    if not face and desc and _NUMBERED.search(desc):
        parts = {m: "" for m in "①②③④⑤"}
        for i, chunk in enumerate(_NUMBERED.split(desc)):
            if i and chunk.strip():
                parts[_NUMBERED.findall(desc)[i - 1]] = chunk.strip().strip("。；; ")
        face = parts["②"] or parts["①"]
        if not outfit or outfit == desc:
            outfit = parts["④"]
    if not face:
        face = character_face(char)
    outfit = re.sub(r"^(穿搭|服装|着装)[：:]\s*", "", outfit)
    if outfit == face:
        outfit = ""
    return face[:MAX_FACE_CHARS].rstrip("，,；; "), outfit[:MAX_OUTFIT_CHARS].rstrip("，,；; ")


GENDER_CN = {"male": "男", "female": "女"}


def _identity(char: dict) -> str:
    """性别 + 年龄段（“男，青年”），没有就空。"""
    return "，".join(x for x in (GENDER_CN.get(str(char.get("gender") or "").lower(), ""),
                                str(char.get("age_group") or "").strip()) if x)


def cast_description(seg: dict, chars: List[dict], scene_no=None) -> str:
    """本段人物外观：名字 + 固定面部特征 + 本场次形态的穿搭（glm-image 不支持参考图，只能写进文字）。"""
    from core.character_forms import form_for_scene

    names = [str(x) for x in (seg.get("characters") or []) if x]
    by_name = {c.get("name"): c for c in chars if c.get("name")}
    parts = []
    for nm in names:
        c = by_name.get(nm)
        if not c:
            continue
        form, _ = form_for_scene(c, scene_no if scene_no is not None else seg.get("scene_no"))
        face, outfit = _face_and_outfit(c, form)
        desc = "；".join(x for x in (_identity(c), face, f"穿搭：{outfit}" if outfit else "") if x)
        parts.append(f"{nm}：{desc}" if desc else nm)
    return "\n".join(parts) if parts else "按四格内容里的身份自然设计，四格保持同一人"


_CLEAN = re.compile(r"\n{3,}")


def storyboard_prompt(body: str, seg: dict, chars: Optional[List[dict]] = None, art_style: str = "",
                      genre: str = "") -> str:
    """出图提示词：四格文案（没有就现算）+ 人物外观 + 画风 填进 STORYBOARD_PROMPT。"""
    body = (body or "").strip() or storyboard_body(seg, genre)
    text = safe_format(
        STORYBOARD_PROMPT,
        storyboard=body,
        cast=cast_description(seg, chars or []),
        art_style=art_style or "按整体设定与人物外观自然呈现，四格统一画风",
    )
    return _CLEAN.sub("\n\n", text).strip()
