"""旁白风格：成片里旁白念多少（按作品选，存在 project.narration_style）。

缺省是“剧情动漫”：我们做的是有剧情的 AI 动漫，不是读小说——剧情靠画面和对白推进，旁白只在几个
设计好的切入点出现（见 CUES），不是每段都有。“小说解说”是另一种内容形态，要选了才用。

拆分镜照旧按原文拆（每段的时长、小镜头、台词时间都按完整旁白算好），然后在这里按风格“删旁白”：
画面已经演出来的旁白不念，只留心理、态度、时间跳转、收尾这类画面演不出来的句子。
- 段时长和小镜头不动：旁白少了，空出来的时间留给画面、环境音和动作音；
- 对白、心声、画外音一个字不动，只动“旁白”；
- 留下的旁白是原句或原句里的半句（逗号、句号断开的一截），不改写，所以仍然都能在原文里找到；
- 被删的旁白记在 seg["cut_lines"]，分镜页能看到，想恢复可以手工加回去。

删哪些：审片的模型给了取舍（seg["keep_narration"]，见 core/shot_agent）就按它的，没给就用代码打分；
两种来源都要过同一道预算（时长占比、句数、单句字数），超了的按打分从低到高再删。
"""
import re
from typing import Dict, List, Optional

from core.shot_timing import _refs, compose_video_prompt, fill_rate, speech_seconds, spoken_chars

DEFAULT_STYLE = "drama"
# ratio：旁白朗读时长最多占段时长的比例；max_lines：每段最多留几句；max_chars：单句最多几个字（超过的只取半句）；
# need_cue：只有落在切入点上的旁白才留（没有切入点的段一句旁白都没有）
STYLES: Dict[str, dict] = {
    "drama": {"name": "剧情动漫", "desc": "剧情靠画面和对白推进，旁白只在切入点出现：交代时间地点、时间跳转、内心与态度、一场戏的收尾。"
                                      "每段最多 2 句、每句不超过 12 个字，多数段没有旁白",
              "ratio": 1 / 3, "max_lines": 2, "max_chars": 12, "need_cue": True},
    "half": {"name": "精简旁白", "desc": "旁白约占一半：画面已经演出来的不念，以整句为单位取舍",
             "ratio": 0.5, "max_lines": 4, "max_chars": None, "need_cue": False},
    "full": {"name": "小说解说", "desc": "原文旁白全念，画面配合旁白（读小说的做法）",
             "ratio": 1.0, "max_lines": None, "max_chars": None, "need_cue": False},
}
CLOSE_MAX_SHOWN = 0.3      # 收尾旁白与小镜头文字的重合超过这个比例，就当它是在复述画面
MIN_BUDGET_SECONDS = 3.0   # 段再短，也容得下一句短旁白（否则 7 秒的段连“三年后……”都放不进）
# 旁白的切入点：什么时候才让旁白出来。对应 _cue_of 的判断，也写进给审片模型的规则里
CUES = {"open": "交代时间地点", "jump": "时间跳转", "mind": "内心与态度", "close": "收尾"}

_SENTENCE_SPLIT = re.compile(r"(?<=[。！？!?；;…])")
_CLAUSE_SPLIT = re.compile(r"(?<=[，,、：:。！？!?；;…—])")
_EDGE = "，,、：:；;—“”「」『』\"' "
# 画面演不出来、值得念出来的：时间跳转
_TIME_CUE = re.compile(r"([一二两三四五六七八九十百几数半\d]+个?(秒|分钟|小时|时辰|天|日|周|月|年)(后|之后|以后|前|过去)|之后|以后|后来|第二天|次日|翌日|当晚|那晚|那天|那一晚|多年|数年|几年|片刻后|不久|转眼|与此同时|另一边|从此|从那)")
# 一场戏开头交代时间地点
_WHEN_WHERE = re.compile(r"(深夜|半夜|凌晨|清晨|黎明|黄昏|傍晚|入夜|夜里|这一年|那一年|这一天|[一二两三四五六七八九十百千\d]+年|城|镇|村|山|巷|街|府|宫|寺|江|河|关)")
# 态度、心理、判断、转折
_MIND_CUE = re.compile(r"(没有|没|不曾|不再|未|别|心|想|知道|明白|觉得|以为|记得|原来|终于|竟|却|仿佛|似乎|再也|只是|而是|其实)")


def style_key(value) -> str:
    key = str(value or "").strip().lower()
    return key if key in STYLES else DEFAULT_STYLE


def list_styles() -> List[dict]:
    return [{"key": k, "name": v["name"], "desc": v["desc"]} for k, v in STYLES.items()]


def style_rule_text(key: str) -> str:
    """给审片模型看的取舍规则（只有非“全念”时才有）。"""
    st = STYLES[style_key(key)]
    if st["ratio"] >= 1:
        return ""
    limit = f"每段最多留 {st['max_lines']} 句" + (f"，每句不超过 {st['max_chars']} 个字（长句只取最有分量的半句）" if st["max_chars"] else "")
    head = ("【旁白取舍】这是有剧情的动漫，不是读小说：剧情靠画面和对白推进，旁白不是每段都有，只在切入点出现。\n"
            "- 切入点只有四种：一场戏开头交代时间地点；时间跳转或换场；画面演不出来的内心、态度、判断；一场戏收尾的余味。\n"
            "- 不在切入点上的旁白一律不留，哪怕写得好。多数段应该一句旁白都没有。\n"
            if st["need_cue"] else
            "【旁白取舍】这部作品的旁白风格是“" + st["name"] + "”：画面能演出来的就不念。\n"
            "- 只留画面演不出来的：心理、态度、判断、时间跳转、一场戏收尾的余味。\n")
    return (head +
            "- 小镜头已经在演的动作、看得见的环境和天气，对应的旁白不留。\n"
            "- 人物正在说话、动作正在发生的那一下不放旁白，留给对白和动作音。\n"
            f"- {limit}；一段里没有值得留的就一句都不留。\n"
            "- 只挑“旁白”，对白、心声、画外音不在此列，照常保留。\n"
            "- 留下的必须是原句，或原句里用逗号、句号断开的一截，一个字不许改。\n"
            "对每一段都在输出里的 narration 给出取舍：{\"seg\": 段号, \"keep\": [\"要留的旁白\"]}，一句都不留就给空数组。")


def _bare(text) -> str:
    return re.sub(r"[\W_]+", "", str(text or ""))


def _bigrams(text: str) -> set:
    t = _bare(text)
    return {t[i:i + 2] for i in range(len(t) - 1)}


def shown_ratio(clause: str, beat_text: str) -> float:
    """这句旁白有多少已经写在小镜头里（按相邻两字的重合算）：越高越像“画面在演的事”。"""
    grams = _bigrams(clause)
    return len(grams & _bigrams(beat_text)) / len(grams) if grams else 0.0


def _pieces(text: str, by_clause: bool) -> List[tuple]:
    """把一句旁白切成候选：[(片段, 片段前面的朗读字数)]。by_clause：逗号也断开；否则只在句号处断。"""
    out, before = [], 0
    for part in (_CLAUSE_SPLIT if by_clause else _SENTENCE_SPLIT).split(str(text or "")):
        clean = part.strip(_EDGE)
        if spoken_chars(clean):
            out.append((clean, before))
        before += spoken_chars(part)
    return out


def _cue_of(clause: str, opening: bool, closing_last: bool) -> str:
    """这截旁白落在哪个切入点上（CUES 的键），都不是返回空串。"""
    if _TIME_CUE.search(clause):
        return "jump"
    if opening and _WHEN_WHERE.search(clause):
        return "open"
    if _MIND_CUE.search(clause):
        return "mind"
    if closing_last:
        return "close"
    return ""


def _score(clause: str, beat_text: str, cue: str) -> float:
    s = -3.0 * shown_ratio(clause, beat_text)       # 小镜头里已经在演的：越像越不该念
    s += {"jump": 3.0, "open": 2.5, "mind": 2.0, "close": 2.0}.get(cue, 0.0)
    if spoken_chars(clause) <= 6:
        s += 1                                       # 短句有分量，也省时间
    return s


def trim_narration(seg: dict, style, keep: Optional[List[str]] = None,
                   opening: bool = False, closing: bool = False) -> int:
    """按旁白风格删这一段的旁白（原地改 seg）。返回删掉 / 截短了几句旁白。

    keep：审片模型说要留的旁白（原句或半句）；None = 没给，用代码打分。seg 里有 keep_narration 时缺省用它。
    opening / closing：这一段是不是一场戏的第一段 / 最后一段（决定“交代时间地点”“收尾”两个切入点开不开）。
    段时长、小镜头的起止不动；小镜头的台词序号按新的台词列表重排。留下的旁白带上 cue（落在哪个切入点）。
    """
    st = STYLES[style_key(style)]
    lines = [ln for ln in (seg.get("lines") or []) if isinstance(ln, dict)]
    if keep is None and isinstance(seg.get("keep_narration"), list):
        keep = seg["keep_narration"]
    seg.pop("keep_narration", None)
    narr = [i for i, ln in enumerate(lines) if ln.get("kind", "narration") == "narration"]
    if st["ratio"] >= 1 or not narr:
        return 0
    try:
        duration = float(seg.get("duration") or 0)
    except (TypeError, ValueError):
        duration = 0.0
    beats = [b for b in (seg.get("beats") or []) if isinstance(b, dict)]

    def beat_text(i: int) -> str:
        mine = [b for b in beats if (i + 1) in _refs(b.get("line_refs"))] or beats
        return "；".join(" ".join(str(b.get(k) or "") for k in ("action", "composition", "expression", "others")) for b in mine)

    # 候选：每句旁白切成的片段；太长的片段（超过单句字数上限）不能留
    cands = []           # {line, text, before, score, picked}
    for i in narr:
        text = str(lines[i].get("text") or "")
        pieces = _pieces(text, by_clause=bool(st["max_chars"]))
        whole = text.strip(_EDGE + "。！？!?…")
        if st["max_chars"] and spoken_chars(whole) <= st["max_chars"]:
            pieces = [(text.strip(), 0)]                 # 整句本来就短：整句作为一个候选，不拆碎
        for clause, before in pieces:
            if st["max_chars"] and spoken_chars(clause) > st["max_chars"]:
                continue
            cands.append({"line": i, "text": clause, "before": before, "beat_text": beat_text(i), "picked": False})
    for n, c in enumerate(cands):
        c["cue"] = _cue_of(c["text"], opening, closing and n == len(cands) - 1)
        if c["cue"] == "close" and shown_ratio(c["text"], c["beat_text"]) >= CLOSE_MAX_SHOWN:
            c["cue"] = ""                                # 最后一句只是在复述画面里的动作：算不上收尾的余味
        c["score"] = _score(c["text"], c["beat_text"], c["cue"])

    if keep is not None:
        wanted = [_bare(k) for k in keep if isinstance(k, str) and _bare(k)]
        for c in cands:
            b = _bare(c["text"])
            c["picked"] = any(w == b or (len(w) >= 3 and (w in b or b in w)) for w in wanted)
            if c["picked"]:
                c["score"] += 10                         # 模型挑的优先，超预算时最后才删
    else:
        for c in cands:
            # 打分为正才值得念；“剧情动漫”还要求落在切入点上，否则这一段就没有旁白
            c["picked"] = c["score"] > 0 and (bool(c["cue"]) or not st["need_cue"])

    # 预算：句数、朗读时长占比；超了从分数低的删起
    budget = max(duration * st["ratio"], MIN_BUDGET_SECONDS) if duration else 0.0
    chosen = sorted((c for c in cands if c["picked"]), key=lambda c: c["score"], reverse=True)
    kept, used = [], 0.0
    for c in chosen:
        sec = speech_seconds(c["text"])
        if st["max_lines"] and len(kept) >= st["max_lines"]:
            break
        if budget and used + sec > budget + 1e-6:
            continue
        kept.append(c)
        used += sec
    kept.sort(key=lambda c: (c["line"], c["before"]))

    # 重建台词列表，记下新旧序号的对应
    new_lines, mapping, cut = [], {}, []
    for i, ln in enumerate(lines):
        if i not in narr:
            mapping[i + 1] = [len(new_lines) + 1]
            new_lines.append(ln)
            continue
        mine = [c for c in kept if c["line"] == i]
        text = str(ln.get("text") or "")
        if len(mine) == 1 and _bare(mine[0]["text"]) == _bare(text):
            mapping[i + 1] = [len(new_lines) + 1]        # 整句保留
            new_lines.append(dict(ln, cue=mine[0]["cue"]) if mine[0]["cue"] else ln)
            continue
        total = max(spoken_chars(text), 1)
        s, e = ln.get("start"), ln.get("end")
        mapping[i + 1] = []
        for c in mine:
            piece = dict(ln, text=c["text"])
            if c["cue"]:
                piece["cue"] = c["cue"]
            if isinstance(s, (int, float)) and isinstance(e, (int, float)) and e > s:
                start = s + (e - s) * c["before"] / total
                piece["start"] = round(start, 1)
                piece["end"] = round(min(start + speech_seconds(c["text"]), e), 1)
            mapping[i + 1].append(len(new_lines) + 1)
            new_lines.append(piece)
        cut.append({"text": text, "kept": "，".join(c["text"] for c in mine),
                    "start": s, "end": e})
    if not cut:
        return 0
    for b in beats:
        b["line_refs"] = [n for r in _refs(b.get("line_refs")) for n in mapping.get(r, [])]
    seg["lines"] = new_lines
    seg["cut_lines"] = cut
    seg["narration_style"] = style_key(style)
    if duration:
        seg["fill_rate"] = fill_rate(new_lines, duration)
    seg["video_prompt"] = compose_video_prompt(seg)      # 【画面】里“此时响起旁白”的位置跟着变
    return len(cut)


def trim_note(style, segments: int, cut: int) -> str:
    st = STYLES[style_key(style)]
    return (f"旁白风格“{st['name']}”：{segments} 段里删掉或截短了 {cut} 句旁白（只在切入点保留旁白，画面已经演出来的不念），"
            "段时长不变，空出来的时间留给画面和音效；删掉的旁白在分镜详情里能看到")


def apply_style(segments: List[dict], style, scene_of=None) -> int:
    """对一集的段依次删旁白。scene_of(段) → 场次标识，用来判断哪一段是一场戏的开头 / 结尾。返回删改的旁白句数。"""
    if STYLES[style_key(style)]["ratio"] >= 1:
        for seg in segments:
            seg.pop("keep_narration", None)
        return 0
    keys = [scene_of(seg) if scene_of else str(seg.get("scene") or "") for seg in segments]
    total = 0
    for i, seg in enumerate(segments):
        total += trim_narration(seg, style,
                                opening=i == 0 or keys[i] != keys[i - 1],
                                closing=i == len(segments) - 1 or keys[i] != keys[i + 1])
    return total
