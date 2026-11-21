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

# 倾听者动作库（{spk}=视线跟随的对象；没有焦点人物时换成“说话的人”）。字符串里不放“说：”，避免被台词保护逻辑误判。
# 时代禁区：这里是兜底库，不知道本剧的时代，所以不放手机、手表、沙发这类现代物件——
# 仙侠廊道里曾因“低头看手机”穿帮（docs/风控问题记录.md §2.3）。现代戏的手机、手表由模型写在 beat.others 里，
# 按时代/题材挑选动作库留给设计稿的 era 字段（方案 §4.4）。MODERN_ITEMS 由测试守住。
MODERN_ITEMS = ("手机", "手表", "沙发", "屏幕", "耳机", "电脑", "键盘")
REACTIONS = (
    "视线跟着{spk}，随对方语气微微点头，偶尔眨眼",
    "身体靠向椅背，重心缓缓换到另一侧，抿一口杯中的酒",
    "垂眸理了理衣袖，指尖捻着袖口，隔几秒抬眼瞥{spk}一下",
    "手指无意识地敲着桌沿，指尖节奏忽快忽慢，目光落在{spk}身上",
    "转动手里的杯子，目光落在杯沿，偶尔抬眼再垂下",
    "双臂抱在胸前，肩膀微微下沉又绷紧，眼神随{spk}移动",
    "身体前倾后又缓缓靠回，手肘撑在膝上，十指交握轻轻摩挲",
    "整理袖口或衣领，偶尔吞咽清嗓，视线在{spk}与桌面之间来回",
    "歪着头看{spk}，眉梢轻挑，嘴角微动，眨眼放慢",
    "抬手摸一下后颈或抹一下嘴角，换了个坐姿，呼吸起伏明显",
    "指腹摩挲着戒指或腕上饰物，视线飘向别处又收回，轻轻吐一口气",
    "端起杯子又放下，目光闪躲一下，喉结滚动",
)
# 需要座位、桌子、杯盏的动作：只在坐着/有桌案的场景里用（雨夜巷战里写“敲桌沿、抿酒、靠椅背”会穿帮）
SEATED_WORDS = ("椅背", "桌沿", "杯", "酒", "膝上", "坐姿", "桌面")
_SEATED_CUES = ("落座", "端坐", "就座", "坐着", "坐于", "对坐", "桌", "席间", "宴", "茶", "酒", "椅", "榻", "案几", "包厢", "沙发")
# 打斗、对峙、追逐等动作戏：旁观者不是在“听人说话”，而是戒备、蓄势、喘息
ACTION_REACTIONS = (
    "重心压低，肩背绷紧，视线锁住{spk}的一举一动",
    "脚下悄悄后撤半步，手指收紧又松开，呼吸急促",
    "侧身戒备，目光随{spk}移动，胸口起伏明显",
    "握紧手中兵器，指节发白，眼神一刻不离{spk}",
    "喘着气稳住身形，衣摆随动作轻摆，下颌绷紧",
    "向旁侧挪了半步调整站位，眼角余光扫着{spk}",
)
# 站着对峙、对话的场面（没有桌椅杯盏）：不理衣袖、不摸戒指、不歪头挑眉，只做站姿下的小幅反应
STANDING_REACTIONS = (
    "立在原地，目光落在{spk}身上，肩背随呼吸缓缓起伏",
    "重心换到另一只脚，视线不离{spk}，手指微微收拢",
    "微微侧身，下颌收紧，注视着{spk}",
    "衣摆被风带动，呼吸放缓，目光随{spk}移动",
    "肩膀微沉又绷紧，眼睫轻动，视线停在{spk}身上",
)
_ACTION_MOODS = ("战", "杀", "险", "爆", "凌厉", "角力", "威压", "挑衅", "破局", "狠", "激烈", "搏", "斗", "惊变", "压迫",
                 "急促", "疾", "拔弩张", "一触即发", "一击", "一掷", "反击", "杀机")
# 动作里出现这些词也算动作戏（情绪词写成“雷霆一击”“孤注一掷”“燕掠雨幕”时靠它认）
_ACTION_VERBS = ("挥刀", "挥匕", "劈", "刺向", "刺入", "踹", "轰出", "格挡", "闪避", "缠斗", "角力", "冲刺", "疾冲", "跃起", "扑向",
                 "刀气", "举刀", "掷出", "刺出", "刺中", "踏前", "前冲", "合围", "结印", "炸裂", "炸开", "欺身", "撞", "下蹬", "倒飞")
# 倒地、昏迷的人：不会“理衣袖、抱臂、歪头看人”
_DOWN_WORDS = ("昏迷", "昏死", "倒地", "倒在", "瘫", "躺", "昏倒", "不省人事")
DOWN_ACTION = "倒在原地不动，只有胸口随呼吸微弱起伏"
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
    """段里的人物：characters + 有画内台词的说话人（去重保序）。"""
    names = [str(n) for n in (shot.get("characters") or []) if n]
    for ln in shot.get("lines") or []:
        sp = ln.get("speaker")
        if ln.get("kind") == "onscreen" and sp and sp != "旁白" and sp not in names:
            names.append(str(sp))
    return list(dict.fromkeys(names))


def segment_people(seg: dict) -> List[str]:
    """本段画面人物：characters + 画内台词说话人，去重保序。"""
    return shot_people(seg)


def filter_positions(positions, people: List[str]) -> str:
    """站位文本按本段在场者裁剪：只保留含本段人物的分句；站位沿抄全场，未入画者的分句不进提示词。"""
    positions = str(positions or "").strip()
    if not positions or not people:
        return positions
    parts = re.split(r"[，；;]", positions)
    keep = [p.strip() for p in parts if p.strip() and any(n in p for n in people)]
    return "，".join(keep)


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
    if hits:
        return hits[0][1]
    # 动作没点名：机位写了拍谁（“沈砚上方，俯拍”）就是谁，别让正在出招的人去“垂眸理衣袖”
    cam = str(beat.get("camera") or "")
    named = [n for n in present if n in cam]
    return named[0] if len(named) == 1 else ""


def _is_seated(shot: dict, beat: dict) -> bool:
    text = f"{shot.get('scene') or ''}；{shot.get('positions') or ''}；{_beat_text(beat)}"
    return any(w in text for w in _SEATED_CUES)


def _is_action(shot: dict) -> bool:
    mood = str(shot.get("mood") or "")
    if any(w in mood for w in _ACTION_MOODS):
        return True
    acts = "；".join(str(b.get("action") or "") for b in (shot.get("beats") or []) if isinstance(b, dict))
    return any(w in acts for w in _ACTION_VERBS)


is_action_shot = _is_action


def is_down(name: str, shot: dict, beat: Optional[dict] = None) -> bool:
    """人物是否倒地/昏迷：站位或小镜头文字里“某某…倒在/昏迷/瘫…”或“倒地的某某”。看到本镜为止（之后才倒的不算）。"""
    beats = [b for b in (shot.get("beats") or []) if isinstance(b, dict)]
    if beat is not None and beat in beats:
        beats = beats[:beats.index(beat) + 1]
    text = f"{shot.get('positions') or ''}；" + "；".join(f"{_beat_text(b)} {b.get('others') or ''}" for b in beats)
    n = re.escape(name)
    w = "|".join(_DOWN_WORDS)
    return bool(re.search(n + r"[^；。,，、]{0,8}(" + w + ")", text) or re.search("(" + w + r")[^；。,，、]{0,3}" + n, text))


def _pool_for(shot: dict, beat: dict, order: tuple, speaking: bool) -> list:
    """非背对者的动作库：动作戏用戒备/蓄势库；其余用倾听库，不在坐席场景时去掉桌椅杯盏，本镜没人开口时去掉“随对方语气”。"""
    if _is_action(shot):
        return list(ACTION_REACTIONS)
    if not _is_seated(shot, beat) and not any(w in str(shot.get("mood") or "") for w in _RELAX):
        return list(STANDING_REACTIONS)
    pool = [REACTIONS[i] for i in order]
    if not _is_seated(shot, beat):
        pool = [p for p in pool if not any(w in p for w in SEATED_WORDS)]
    if not speaking:
        pool = [p for p in pool if "语气" not in p] or pool
    return pool


def _speaking(shot: dict, beat: dict) -> bool:
    lines = shot.get("lines") or []
    return any(1 <= r <= len(lines) and lines[r - 1].get("kind") == "onscreen" for r in (beat.get("line_refs") or []))


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
        if not focus and present:
            # 动作里只写“他/她”没点名：把排在最前的在场者当焦点，不能让他给自己当旁观者（“沈砚视线跟着说话的人”）
            focus = present[0]
        speaking = _speaking(shot, b)
        spk = focus if (focus and (speaking or _is_action(shot))) else (focus or "说话的人")
        size = str(b.get("shot_size") or "")
        far = "远景" in size or "全景" in size
        used_here: set = set()
        items = []
        for n in [x for x in present if x != focus]:
            pi = people.index(n) if n in people else 0
            if is_down(n, shot, b):
                items.append((n, DOWN_ACTION))
                continue
            back = is_back(n, shot, b)
            pool = list(BACK_ACTIONS) if back else _pool_for(shot, b, order, speaking)
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
