"""分镜配音口径兜底：一个镜头只配一种声音。

配音页按 character_name 选音色并朗读整段 text，所以 text 里不能把旁白叙述和角色台词拼在一起。
模型偶尔仍会输出“赵虎踉跄着稳住身形：你身上藏了什么？”或““哟”赵虎跨进门来”这类混合文本，
这里按冒号/引号拆成“旁白一镜 + 台词一镜”，台词说话人从紧邻的叙述里找已知角色名。
"""
import re

from core.shot_timing import estimate_duration, spoken_chars

NARRATOR = "旁白"
_QUOTE_PATTERN = re.compile(r"[“「\"]([^”」\"]+)[”」\"]")
_COLON_PATTERN = re.compile(r"[：:]")
_MIN_NARRATION_CHARS = 6  # 少于这么多字的叙述（如“赵虎道”）不单独成镜


def _strip_quotes(s: str) -> str:
    return s.strip().strip("“”「」\"'‘’").strip()


def _segments(text: str):
    """把 text 切成 [(kind, content)]，kind 为 narration / dialogue；不是混合文本返回 None。"""
    if _QUOTE_PATTERN.search(text):
        segs, pos = [], 0
        for m in _QUOTE_PATTERN.finditer(text):
            if m.start() > pos:
                segs.append(("narration", text[pos:m.start()]))
            segs.append(("dialogue", m.group(1)))
            pos = m.end()
        if pos < len(text):
            segs.append(("narration", text[pos:]))
    else:
        m = _COLON_PATTERN.search(text)
        if not m:
            return None
        segs = [("narration", text[:m.start()]), ("dialogue", text[m.end():])]
    cleaned = []
    for kind, content in segs:
        content = _strip_quotes(content).strip("：:，,").strip()
        if not content:
            continue
        if kind == "narration" and spoken_chars(content) < _MIN_NARRATION_CHARS:
            cleaned.append(("tag", content))  # 说话人提示，不单独配音
            continue
        cleaned.append((kind, content))
    kinds = {k for k, _ in cleaned}
    if "dialogue" not in kinds:
        return None
    return cleaned


def _find_speaker(segs, idx, names, fallback):
    """优先在台词前面的叙述里找最靠近的角色名，再看后面的叙述，最后用回退值。"""
    def last_name_in(s):
        best, best_pos = None, -1
        for n in names:
            p = s.rfind(n)
            if p > best_pos:
                best, best_pos = n, p
        return best
    for j in range(idx - 1, -1, -1):
        if segs[j][0] != "dialogue":
            hit = last_name_in(segs[j][1])
            if hit:
                return hit
            break
    for j in range(idx + 1, len(segs)):
        if segs[j][0] != "dialogue":
            hit = last_name_in(segs[j][1])
            if hit:
                return hit
            break
    return fallback


def split_mixed_voice(shots: list, known_names) -> list:
    """把旁白和台词混在一个 text 里的镜头拆开；返回新的镜头列表（未拆分的原样保留）。"""
    out, changed = [], False
    for shot in shots:
        text = (shot.get("text") or "").strip()
        segs = _segments(text) if text else None
        if not segs:
            out.append(shot)
            continue
        cur = shot.get("character_name") or NARRATOR
        names = sorted({n for n in (list(known_names) + list(shot.get("characters") or []) + [cur])
                        if n and n != NARRATOR}, key=len, reverse=True)
        fallback = cur if cur != NARRATOR else None
        voiced = [(k, c) for k, c in segs if k in ("narration", "dialogue")]
        pieces = []
        for i, (kind, content) in enumerate(segs):
            if kind == "narration":
                pieces.append((NARRATOR, content))
            elif kind == "dialogue":
                speaker = _find_speaker(segs, i, names, fallback)
                if not speaker:
                    pieces = None  # 找不到说话人：不动，避免把台词错配给别人
                    break
                pieces.append((speaker, content))
        if not pieces or (len(voiced) == 1 and pieces[0][0] == cur and pieces[0][1] == text):
            out.append(shot)
            continue
        # 相邻同一说话人的片段合并
        merged = []
        for speaker, content in pieces:
            if merged and merged[-1][0] == speaker:
                merged[-1] = (speaker, merged[-1][1] + content)
            else:
                merged.append((speaker, content))
        for speaker, content in merged:
            new = dict(shot)
            new["character_name"] = speaker
            new["text"] = content
            if len(merged) > 1:
                new["duration"] = estimate_duration(content)
            out.append(new)
        changed = True
    if changed and out:
        start = out[0].get("shot_no") or 1
        try:
            start = int(start)
        except (TypeError, ValueError):
            start = 1
        for i, s in enumerate(out):
            s["shot_no"] = start + i
    return out
