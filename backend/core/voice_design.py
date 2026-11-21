"""音色设计：每个角色一份“声音设定”，全片照这一份说话。

以前只有两样东西，而且互不相干：
- voice：提取角色时顺手写的一句“17岁男性，清亮”（从固定的声音属性库里挑一个词）；
- voice_name：配音用的内置音色库 id（十来个里挑一个）。
成片里的人声是视频模型按提示词生成的，而提示词里角色怎么发声一个字都没写，旁白写死“沉稳青年男声”——
所以同一个角色这一段是一个嗓子、下一段换一个，谁说话都差不多。

这里把音色当成和长相、穿着一样的角色设定来做：
- 声音设定 voice_design = {pitch 音高, timbre 音质, pace 语速, manner 说话方式, habit 说话习惯}；
- 全体角色放在一起设计（design_cast）：同场对戏的人要一听就分得开，不能两个主角都是“低沉磁性”；
- voice_line() 把设定写成一句固定的话，每一段的视频提示词都用同一句（逐字相同，模型才认成同一个人）；
- 旁白也是作品的设定（narrator_line），不再写死；
- 内置音色库退到配音环节做匹配：按声音设定去挑最接近的一个（core.voice_matcher）。

提示词在注册表里（core/prompts 的 voice_design），和其他环节一样能查看、按题材加变体。
"""
import logging
import re
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

PROMPT_KEY = "voice_design"
MAX_TOKENS = 4096
MAX_CAST = 24                 # 一次设计的角色数上限（主角、配角优先）

# 音高、语速给固定档位（页面下拉，也方便比较两个角色是否撞了）；其余是短句
PITCHES = ["低沉", "偏低", "中等", "偏高", "高亮"]
PACES = ["慢", "偏慢", "适中", "偏快", "快"]
FIELDS = ("pitch", "timbre", "pace", "manner", "habit")
FIELD_CN = {"pitch": "音高", "timbre": "音质", "pace": "语速", "manner": "说话方式", "habit": "说话习惯"}
_LIMITS = {"pitch": 4, "timbre": 12, "pace": 4, "manner": 24, "habit": 24}

SOURCE_AI, SOURCE_RULE, SOURCE_USER = "ai", "rule", "user"
DEFAULT_NARRATOR = "沉稳青年男声"
MAX_LINE = 46                 # 写进视频提示词的那一句的长度上限
MAX_NARRATOR = 30

_GENDER_CN = {"male": "男", "female": "女"}
_AGE_WORD = {("male", "少年"): "少年", ("female", "少年"): "少女", ("male", "青年"): "青年男", ("female", "青年"): "青年女",
             ("male", "中年"): "中年男", ("female", "中年"): "中年女", ("male", "暮年"): "老年男", ("female", "暮年"): "老年女"}
# 没让模型设计时的兜底：按年龄段给音高、语速，按气质词给音质和说话方式
_AGE_PITCH = {("male", "少年"): "偏高", ("male", "青年"): "中等", ("male", "中年"): "偏低", ("male", "暮年"): "低沉",
              ("female", "少年"): "高亮", ("female", "青年"): "偏高", ("female", "中年"): "中等", ("female", "暮年"): "偏低"}
_AGE_PACE = {"少年": "偏快", "青年": "适中", "中年": "适中", "暮年": "偏慢"}
_TRAIT_RULES = (
    (("阳刚", "豪迈", "热血", "爽朗"), "洪亮", "中气足，句尾干脆"),
    (("阴", "邪", "狠"), "沙哑", "压着嗓子，慢条斯理"),
    (("温柔", "温和", "婉"), "柔和", "轻声细语，尾音放软"),
    (("阳光", "开朗", "少年感"), "清亮", "语气上扬，带笑意"),
    (("威严", "沉稳", "稳重"), "厚重", "不紧不慢，字字落地"),
    (("清冷", "冷", "孤"), "清澈", "平直少起伏，话短"),
    (("憨", "朴实", "木讷"), "沉实", "一顿一顿，实打实"),
    (("妖", "媚", "魅"), "柔媚", "拖长尾音，带气声"),
    (("苍老", "慈祥"), "苍劲", "气息慢，带颤音"),
    (("活泼", "俏皮", "灵动", "甜"), "清甜", "跳着说，连珠似的"),
    (("轻浮", "油滑"), "亮堂", "吊儿郎当，尾音上挑"),
)


def _clean(value, limit: int) -> str:
    """字段值：去引号、换行和首尾标点，超长截断。"""
    s = re.sub(r"[\"“”\r\n]", "", str(value or "")).strip(" ，,。；;、")
    return s[:limit]


def _pick(value, options: List[str], default: str) -> str:
    """档位字段：模型写“偏高一点”“语速较快”之类也认到最接近的档。"""
    s = _clean(value, 12)
    if s in options:
        return s
    for o in sorted(options, key=len, reverse=True):
        if o in s:
            return o
    return default


def normalize_design(raw) -> Optional[dict]:
    """模型或页面给的声音设定 → 规整后的字典；没有可用内容返回 None。"""
    if not isinstance(raw, dict):
        return None
    out = {
        "pitch": _pick(raw.get("pitch"), PITCHES, "") if raw.get("pitch") else "",
        "timbre": _clean(raw.get("timbre"), _LIMITS["timbre"]),
        "pace": _pick(raw.get("pace"), PACES, "") if raw.get("pace") else "",
        "manner": _clean(raw.get("manner"), _LIMITS["manner"]),
        "habit": _clean(raw.get("habit"), _LIMITS["habit"]),
    }
    return out if any(out.values()) else None


def _gender(char: dict) -> str:
    g = str(char.get("gender") or "").lower()
    return g if g in _GENDER_CN else ""


def _age(char: dict) -> str:
    a = str(char.get("age_group") or "")
    return next((k for k in ("少年", "青年", "中年", "暮年") if k in a), "")


def fallback_design(char: dict) -> dict:
    """不调模型的兜底设定：按性别、年龄段、气质词推一份（比空着强，但各角色之间不保证拉得开）。"""
    g, a = _gender(char) or "male", _age(char) or "青年"
    trait = " ".join(str(char.get(k) or "") for k in ("trait", "voice"))
    timbre, manner = "", ""
    for words, t, m in _TRAIT_RULES:
        if any(w in trait for w in words):
            timbre, manner = t, m
            break
    if not timbre:
        # 提取时写的 voice 形如“17岁男性，清亮”：逗号后那个词就是音质
        tail = re.split(r"[，,]", str(char.get("voice") or ""))[-1].strip()
        timbre = tail if 0 < len(tail) <= 6 and "岁" not in tail else ("清亮" if a in ("少年", "青年") else "厚重")
    return {"pitch": _AGE_PITCH.get((g, a), "中等"), "timbre": timbre, "pace": _AGE_PACE.get(a, "适中"),
            "manner": manner, "habit": ""}


def design_of(char: dict) -> Optional[dict]:
    """角色已有的声音设定（规整过）；没有返回 None。"""
    return normalize_design((char or {}).get("voice_design"))


def _who(char: dict) -> str:
    """“少年声”“中年女声”：一听就知道是什么人在说话。"""
    word = _AGE_WORD.get((_gender(char), _age(char)))
    if word:
        return f"{word}声"
    g = _GENDER_CN.get(_gender(char))
    return f"{g}声" if g else ""


def voice_line(char: dict) -> str:
    """写进视频提示词的那一句：同一个角色每一段逐字相同。

    有声音设定按设定写（“少年声，音高偏高，清亮带少年气，语速偏快，语气上扬”）；
    没有就用提取时写的 voice 原话；都没有返回空串（提示词里不写，和以前一样）。
    """
    d = design_of(char)
    if not d:
        return _clean((char or {}).get("voice"), MAX_LINE)
    bits = [_who(char)]
    if d["pitch"]:
        bits.append(f"音高{d['pitch']}")
    if d["timbre"]:
        bits.append(d["timbre"])
    if d["pace"]:
        bits.append(f"语速{d['pace']}")
    line = "，".join(b for b in bits if b)
    for extra in (d["manner"], d["habit"]):      # 说话方式、习惯能放下才放，不把一句话截成半句
        if extra and len(line) + 1 + len(extra) <= MAX_LINE:
            line += "，" + extra
    return line


def narrator_line(project: Optional[dict]) -> str:
    """旁白的声音：作品里设过就用作品的，没有用缺省。"""
    return _clean((project or {}).get("narrator_voice"), MAX_NARRATOR) or DEFAULT_NARRATOR


def voices_for(names: List[str], chars: List[dict]) -> Dict[str, str]:
    """这些说话人各自的那一句。没有设定的人不出现。"""
    by_name = {c.get("name"): c for c in chars or [] if isinstance(c, dict)}
    out = {}
    for n in names or []:
        line = voice_line(by_name.get(n) or {})
        if line:
            out[n] = line
    return out


def clashes(chars: List[dict]) -> List[str]:
    """撞音色的角色：同性别、音高和音质都一样的主角或配角，观众只听声音分不出是谁。"""
    seen: Dict[Tuple[str, str, str], List[str]] = {}
    for c in chars or []:
        if str(c.get("importance") or "support") not in ("main", "support"):
            continue
        d = design_of(c)
        if not d or not (d["pitch"] and d["timbre"]):
            continue
        seen.setdefault((_gender(c), d["pitch"], d["timbre"]), []).append(str(c.get("name") or ""))
    return [f"{'、'.join(names)} 的声音设定几乎一样（音高{k[1]}、{k[2]}），同场对话时听不出是谁，建议改开其中一个"
            for k, names in seen.items() if len(names) > 1]


def cast_block(chars: List[dict]) -> str:
    """给模型看的角色表：名字、身份、性别年龄、气质、长相与人物简介（声音要和人对得上）。"""
    from core.character_forms import character_face
    role = {"main": "主角", "support": "配角", "extra": "路人"}
    lines = []
    for c in chars:
        tags = "，".join(t for t in (role.get(str(c.get("importance") or "")), _GENDER_CN.get(_gender(c)),
                                    str(c.get("age_group") or "").strip(), str(c.get("trait") or "").strip()) if t)
        desc = _clean(c.get("description") or character_face(c), 60)
        old = _clean(c.get("voice"), 20)
        lines.append(f"- {c.get('name')}" + (f"（{tags}）" if tags else "") + (f"：{desc}" if desc else "")
                     + (f"；原音色备注：{old}" if old else ""))
    return "\n".join(lines)


def pick_cast(chars: List[dict], overwrite: bool = False) -> List[dict]:
    """要交给模型设计的角色：主角、配角优先，最多 MAX_CAST 个；手改过的（source=user）不动，
    已经设计过的只有 overwrite 才重做。"""
    order = {"main": 0, "support": 1, "extra": 2}
    todo = []
    for c in chars or []:
        if c.get("voice_design_source") == SOURCE_USER and design_of(c):
            continue
        if design_of(c) and c.get("voice_design_source") == SOURCE_AI and not overwrite:
            continue
        todo.append(c)
    todo.sort(key=lambda c: order.get(str(c.get("importance") or "support"), 1))
    return todo[:MAX_CAST]


async def design_cast(llm, chars: List[dict], todo: List[dict], novel: str = "",
                      variant: Optional[str] = None) -> Tuple[Dict[str, dict], str, str]:
    """让模型给 todo 里的角色设计声音。chars 是全体角色（已定下来的声音也给模型看，新设计的要和它们分开）。

    返回 ({角色名: 声音设定}, 旁白声音或空串, 给用户看的一句说明)。失败不抛：返回空字典，由调用方走兜底。
    """
    from core.prompt_registry import build_messages
    if not todo:
        return {}, "", ""
    fixed = [f"- {c.get('name')}：{voice_line(c)}" for c in chars
             if c not in todo and design_of(c) and voice_line(c)]
    messages = build_messages(
        PROMPT_KEY, variant=variant, cast_block=cast_block(todo),
        fixed_block="\n".join(fixed) or "（暂无）", novel_text=(novel or "")[:3000] or "（未提供）")
    try:
        raw = await llm.chat_json(messages, max_tokens=MAX_TOKENS)
    except Exception as e:
        logger.warning("音色设计失败，改用按年龄气质推的兜底: %s", e)
        return {}, "", f"模型没能完成设计（{str(e)[:60]}），先按年龄和气质给了一份基础设定，可以再点一次重试"
    items = raw.get("voices") if isinstance(raw, dict) else None
    names = {str(c.get("name")) for c in todo}
    out: Dict[str, dict] = {}
    for it in items if isinstance(items, list) else []:
        if not isinstance(it, dict) or str(it.get("name")) not in names:
            continue
        d = normalize_design(it)
        if d:
            out[str(it["name"])] = d
    narrator = _clean(raw.get("narrator"), MAX_NARRATOR) if isinstance(raw, dict) else ""
    note = "" if out else "模型没有返回可用的设计，先按年龄和气质给了一份基础设定"
    return out, narrator, note
