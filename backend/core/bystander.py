"""T-273 非焦点人物的持续微动作（其余在场者）。

视频模型严格按小镜头文字执行：没写的人就定格成木头。所以每个小镜头里出现的每个人都要有动作——
焦点人物写 action，其余在场者写 beat.others（逐人）。模型没写 others 的老数据由这里按情绪基调与站位兜底：
在场人物 - 焦点人物 = 倾听者，逐人从动作库里挑，同镜头内不同人不同动作，同一人相邻小镜头不重复。
背对镜头的人用背影动作库（呼吸起伏、肩部微动、偶尔转头/换姿势）；远景里幅度写大一点。
"""
import re
from typing import Dict, List, Optional

KEEP_MOVING = "均保持在画面内持续有微动作，不静止定格"
LABEL = "其余在场者："

# 倾听者动作库（{spk}=视线跟随的对象；没有焦点人物时换成“说话的人”）。字符串里不放“说：”，避免被台词保护逻辑误判
REACTIONS = (
    "视线跟着{spk}，随对方语气微微点头，偶尔眨眼",
    "身体靠向椅背或沙发背，重心缓缓换到另一侧，抿一口杯中的酒",
    "低头看手机，拇指偶尔滑动屏幕，隔几秒抬眼瞥{spk}一下",
    "手指无意识地敲着桌沿，指尖节奏忽快忽慢，目光落在{spk}身上",
    "转动手里的杯子，目光落在杯沿，偶尔抬眼再垂下",
    "双臂抱在胸前，肩膀微微下沉又绷紧，眼神随{spk}移动",
    "身体前倾后又缓缓靠回，手肘撑在膝上，十指交握轻轻摩挲",
    "整理袖口或衣领，偶尔吞咽清嗓，视线在{spk}与桌面之间来回",
    "歪着头看{spk}，眉梢轻挑，嘴角微动，眨眼放慢",
    "抬手摸一下后颈或抹一下嘴角，换了个坐姿，呼吸起伏明显",
    "指腹摩挲着戒指或手表，视线飘向别处又收回，轻轻吐一口气",
    "端起杯子又放下，目光闪躲一下，喉结滚动",
)
# 背对镜头的人：看不到脸，靠背影的呼吸、肩部和姿势变化
BACK_ACTIONS = (
    "背对镜头，后背随呼吸缓缓起伏，肩膀偶尔微微耸动",
    "背对镜头，头微微侧向{spk}的方向，重心从一只脚换到另一只，肩背放松又收紧",
    "背对镜头，手臂小幅调整姿势，偶尔转头又转回，肩部随呼吸轻动",
)
FAR_SUFFIX = "，动作幅度稍大以便远景看得清"

_TENSE = ("紧张", "压抑", "对峙", "愤怒", "冷", "悲", "危", "凝重", "沉重", "尴尬")
_RELAX = ("轻松", "欢", "爽", "温馨", "甜", "喜", "暧昧", "热闹", "放松")
# 偏好顺序（REACTIONS 下标）：紧张偏紧绷小动作，轻松偏放松动作，其余按库顺序
_TENSE_ORDER = (3, 5, 11, 10, 7, 0, 9, 4, 6, 8, 1, 2)
_RELAX_ORDER = (1, 2, 8, 4, 9, 0, 6, 7, 3, 10, 5, 11)

_CLOSE = ("特写", "大特写", "近景")   # 整词相等或以特写结尾；“中近景”不算（画面里还有别人）
_ALONE = ("独自", "单独", "一人")
_EMPTY = ("空镜", "无人")


def _order(mood: str) -> tuple:
    mood = str(mood or "")
    if any(w in mood for w in _TENSE):
        return _TENSE_ORDER
    if any(w in mood for w in _RELAX):
        return _RELAX_ORDER
    return tuple(range(len(REACTIONS)))


def shot_people(shot: dict) -> List[str]:
    """段里的人物：characters + 有画内台词的说话人；再补站位里按名字出现的（去重保序）。"""
    names = [str(n) for n in (shot.get("characters") or []) if n]
    for ln in shot.get("lines") or []:
        sp = ln.get("speaker")
        if ln.get("kind") == "onscreen" and sp and sp != "旁白" and sp not in names:
            names.append(str(sp))
    return list(dict.fromkeys(names))


def _beat_text(b: dict) -> str:
    return " ".join(str(b.get(k) or "") for k in ("action", "composition", "expression"))


def is_back(name: str, shot: dict, beat: dict) -> bool:
    """人物是否背对镜头：站位或小镜头文字里“某某…背对/背朝/背向/背影”或“背对…的某某”。"""
    text = f"{shot.get('positions') or ''}；{_beat_text(beat)}"
    n = re.escape(name)
    return bool(re.search(n + r"[^；。,，]{0,8}(背对|背朝|背向|背影|背身)", text)
                or re.search(r"(背对|背朝|背向)[^；。,，]{0,6}" + n, text))


def present_people(shot: dict, beat: dict, people: List[str]) -> List[str]:
    """该小镜头画面里的人物：特写只算被点名的；独自/空镜只算被点名的；其余景别算段里全部人物（点名者在前）。"""
    text = _beat_text(beat)
    named = [n for n in people if n in text]
    named.sort(key=text.find)
    size = str(beat.get("shot_size") or "")
    if size.strip() in _CLOSE or size.endswith("特写") or any(w in text for w in _ALONE):
        return named
    if not named and (any(w in text for w in _EMPTY) or str(beat.get("expression") or "").strip() == "无"):
        return []
    rest = [n for n in people if n not in named]
    return named + rest


def focus_of(shot: dict, beat: dict, present: List[str]) -> str:
    """焦点人物：本镜发声的画内说话人；否则动作里最先点名的人；都没有返回空。"""
    lines = shot.get("lines") or []
    for r in beat.get("line_refs") or []:
        if 1 <= r <= len(lines) and lines[r - 1].get("kind") == "onscreen" and lines[r - 1].get("speaker") in present:
            return lines[r - 1]["speaker"]
    text = str(beat.get("action") or "")
    hits = sorted((text.find(n), n) for n in present if n in text)
    return hits[0][1] if hits else ""


def plan_others(shot: dict) -> List[List[tuple]]:
    """每个小镜头的非焦点在场者动作 [(人名, 动作)]。beat.others 写了就不兜底（返回空列表，由调用方用原文）。

    同镜头内不同人不同动作；同一人相邻小镜头不重复；背对镜头的人用背影动作库。"""
    people = shot_people(shot)
    beats = [b for b in (shot.get("beats") or []) if isinstance(b, dict)]
    order = _order(shot.get("mood"))
    prev: Dict[str, str] = {}
    out: List[List[tuple]] = []
    for bi, b in enumerate(beats):
        if str(b.get("others") or "").strip():
            out.append([])
            continue
        present = present_people(shot, b, people)
        focus = focus_of(shot, b, present)
        spk = focus or "说话的人"
        size = str(b.get("shot_size") or "")
        far = "远景" in size or "全景" in size
        used_here: set = set()
        items = []
        for n in [x for x in present if x != focus]:
            pi = people.index(n) if n in people else 0
            back = is_back(n, shot, b)
            pool = list(BACK_ACTIONS) if back else [REACTIONS[i] for i in order]
            # 每个人从自己的起点轮转，避免所有人从库首条开始撞车
            start = (pi * 3 + bi) % len(pool)
            pool = pool[start:] + pool[:start]
            pick = next((p for p in pool if p not in used_here and p != prev.get(n)), pool[0])
            used_here.add(pick)
            prev[n] = pick
            text = pick.format(spk=spk)
            if far:
                text += FAR_SUFFIX
            items.append((n, text))
        out.append(items)
    return out


def others_phrase(items: List[tuple]) -> str:
    """[(人名, 动作)] → “其余在场者：A…；B…，均保持…”；没有人返回空。"""
    if not items:
        return ""
    return LABEL + "；".join(f"{n}{t}" for n, t in items) + "；" + KEEP_MOVING


def explicit_phrase(text: str) -> str:
    """模型写的 beat.others 原文 → 带前缀与持续动作声明。"""
    t = str(text or "").strip().rstrip("，,。；;")
    if not t or t in ("无", "空镜", "-", "—"):
        return ""
    return f"{LABEL}{t}；{KEEP_MOVING}"


def beat_phrases(shot: dict) -> List[str]:
    """每个小镜头的“其余在场者：…”完整短语（显式 others 优先，否则兜底），没人为空串。"""
    beats = [b for b in (shot.get("beats") or []) if isinstance(b, dict)]
    fallback = plan_others(shot)
    return [explicit_phrase(b.get("others")) or others_phrase(fallback[i]) for i, b in enumerate(beats)]
