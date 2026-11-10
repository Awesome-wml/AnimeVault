"""分镜时长规则：模板文字和落库兜底共用同一套常量与估算函数。

两套口径：
- 视频段（当前格式，一条 = 一次视频生成）：normalize_segment / retime_segment。段时长目标取所选模型的
  max_duration，段内 lines 按朗读时长（4.5 字/秒）校正起止、不重叠、不越界；朗读总时长装不下时在句子边界
  拆成两段（代码兜底）。
- 旧格式（一镜一声，没有 lines）：estimate_duration / normalize_duration，只用于旧数据和
  用户自定义的旧版拆分镜模板。时长 ≈ 朗读时长 + 1 秒余量，3 到 15 秒。
"""
import math
import re

CHARS_PER_SECOND = 4.5      # 中文朗读语速
REACTION_SECONDS = 1        # 动作与反应余量
MIN_SECONDS = 3
MAX_SECONDS = 15
DEVIATION_RATIO = 2         # 模型时长超过估算的这个倍数视为明显偏离
CORRECTED_EXTRA_SECONDS = 2  # 明显偏离时收回到“估算 + 这点余量”

# 不计入朗读字数的标点与空白
_NON_SPOKEN = re.compile(r"[\s，。！？、；：,.!?;:…—\-“”‘’「」『』《》（）()【】\[\]\"']")


def spoken_chars(text: str) -> int:
    """朗读字数：去掉标点和空白后的字符数。"""
    return len(_NON_SPOKEN.sub("", text or ""))


def estimate_duration(text: str) -> int:
    """按朗读字数估算单镜时长（秒）。"""
    est = math.ceil(spoken_chars(text) / CHARS_PER_SECOND) + REACTION_SECONDS
    return int(min(max(est, MIN_SECONDS), MAX_SECONDS))


def normalize_duration(model_value, text: str) -> float:
    """校正模型给的时长：缺失或读不完时用估算值；超过估算 2 倍时收回到“估算 + 2 秒”；上限 15 秒。"""
    est = estimate_duration(text)
    try:
        d = float(model_value)
    except (TypeError, ValueError):
        return float(est)
    if d < est:
        d = est
    elif d > est * DEVIATION_RATIO:
        d = est + CORRECTED_EXTRA_SECONDS
    return float(min(max(d, MIN_SECONDS), MAX_SECONDS))


# ============================================================
# 视频段（一条 = 一次视频生成）
# ============================================================
NARRATOR = "旁白"
LINE_KINDS = ("narration", "inner", "onscreen", "offscreen")
LINE_GAP = 0.3          # 相邻两句之间至少留的秒数
LEAD_SECONDS = 0.5      # 模型没给起点时，第一句从这里开始
TAIL_SECONDS = 0.3      # 最后一句至少在段尾前这么多秒结束
ACTION_SECONDS = 1.0    # 段内留给动作起收的秒数：段时长至少 = 朗读总时长 + 这点
SPEECH_MARGIN = 2.0     # 台词预算：每段朗读字数 ≤ (段最长时长 - 这点) × 4.5，超出在句子边界拆到下一段
MIN_LINE_SECONDS = 0.6  # 极短的句子（如“嗯”）也至少占这么久
MIN_BEAT_SECONDS = 0.8  # 段内小镜头至少这么长
_SENTENCE_END = re.compile(r"(?<=[。！？!?；;…])")
_CLAUSE_END = re.compile(r"(?<=[，,、：:])")
_STRIP_QUOTES = "“”「」『』\"'‘’ "


def speech_seconds(text: str) -> float:
    """一句话的朗读秒数（不加余量）。"""
    return max(spoken_chars(text) / CHARS_PER_SECOND, MIN_LINE_SECONDS) if spoken_chars(text) else 0.0


def is_segment(item: dict) -> bool:
    """是不是视频段格式（有 lines 或 beats）；否则按旧的一镜一声处理。"""
    return isinstance(item, dict) and (bool(item.get("lines")) or bool(item.get("beats")))


def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None  # 排除 NaN


def _r1(x: float) -> float:
    return round(x + 1e-9, 1)


def normalize_lines(raw_lines) -> list:
    """规整 lines：去空、去引号、补 kind/speaker；旁白一律 narration，narration 的 speaker 统一为旁白。"""
    out = []
    for ln in raw_lines or []:
        if isinstance(ln, str):
            ln = {"speaker": NARRATOR, "text": ln}
        if not isinstance(ln, dict):
            continue
        text = str(ln.get("text") or "").strip().strip(_STRIP_QUOTES).strip()
        if not spoken_chars(text):
            continue
        speaker = str(ln.get("speaker") or "").strip() or NARRATOR
        kind = str(ln.get("kind") or "").strip().lower()
        if kind not in LINE_KINDS:
            kind = "narration" if speaker == NARRATOR else "onscreen"
        if speaker == NARRATOR:
            kind = "narration"
        if kind == "narration":
            speaker = NARRATOR
        out.append({"speaker": speaker, "text": text, "kind": kind,
                    "start": _num(ln.get("start")), "end": _num(ln.get("end"))})
    return out


def _split_text(text: str, limit_seconds: float) -> list:
    """一句话朗读超过 limit_seconds 时，按句号/问号等、再按逗号切开，每块尽量装满。"""
    if speech_seconds(text) <= limit_seconds:
        return [text]
    parts = [p for p in _SENTENCE_END.split(text) if p.strip()]
    if len(parts) <= 1:
        parts = [p for p in _CLAUSE_END.split(text) if p.strip()]
    if len(parts) <= 1:  # 没有标点：按字数硬切
        n = max(int(limit_seconds * CHARS_PER_SECOND), 1)
        return [text[i:i + n] for i in range(0, len(text), n)]
    chunks, cur = [], ""
    for p in parts:
        if cur and speech_seconds(cur + p) > limit_seconds:
            chunks.append(cur)
            cur = p
        else:
            cur += p
    if cur:
        chunks.append(cur)
    out = []
    for c in chunks:
        out.extend(_split_text(c, limit_seconds) if speech_seconds(c) > limit_seconds and c != text else [c])
    return out


def lines_total_seconds(lines: list) -> float:
    """段内朗读总时长（含句间留白）。"""
    secs = [speech_seconds(ln["text"]) for ln in lines]
    return sum(secs) + LINE_GAP * max(len(secs) - 1, 0)


def _needed_duration(lines: list) -> int:
    return int(math.ceil(lines_total_seconds(lines) + ACTION_SECONDS - 1e-9)) if lines else 0


def _pick_duration(model_value, lines: list, model: dict) -> int:
    """段时长：模型给了就用（不短于朗读所需），没给按目标 max_duration；内容很少（不足 6 秒）时取实际所需；
    都钳到 [模型最短, 模型最长]。"""
    lo, hi = int(model["min_duration"]), int(model["max_duration"])
    need = _needed_duration(lines)
    d = _num(model_value)
    if d is None or d <= 0:
        from core.video_models import SHORT_SEGMENT_SECONDS
        d = hi if (need >= SHORT_SEGMENT_SECONDS or not lines) else need
    d = max(int(math.ceil(d - 1e-9)), need)
    return int(min(max(d, lo), hi))


def time_lines(lines: list, duration: float) -> bool:
    """按朗读时长给每句定起止：不重叠、不越界，尽量贴近模型给的起点。返回是否装不下（溢出）。"""
    if not lines:
        return False
    limit_end = max(duration - TAIL_SECONDS, 0)
    cur = 0.0
    for i, ln in enumerate(lines):
        r = speech_seconds(ln["text"])
        desired = ln.get("start")
        floor = cur + (LINE_GAP if i else 0.0)
        if desired is None or desired < 0:
            desired = floor if i else LEAD_SECONDS
        start = max(desired, floor)
        ln["start"], ln["end"] = start, start + r
        cur = ln["end"]
    overflow = False
    if lines[-1]["end"] > limit_end:
        # 从后往前收：最后一句贴着段尾，前面的依次往前挪
        limit = limit_end
        for ln in reversed(lines):
            r = ln["end"] - ln["start"]
            end = min(ln["end"], limit)
            ln["start"], ln["end"] = end - r, end
            limit = ln["start"] - LINE_GAP
        if lines[0]["start"] < 0:
            # 留白都压掉也装不下：从 0 起顺排，超出段尾的截在段尾（只会出现在手工改台词后）
            cur = 0.0
            for ln in lines:
                r = ln["end"] - ln["start"]
                ln["start"] = cur
                ln["end"] = cur + r
                cur = ln["end"]
            overflow = lines[-1]["end"] > duration + 1e-6
            for ln in lines:
                ln["start"] = min(ln["start"], duration)
                ln["end"] = min(ln["end"], duration)
    for ln in lines:
        ln["start"], ln["end"] = _r1(ln["start"]), _r1(ln["end"])
    return overflow


def _refs(value) -> list:
    if not isinstance(value, list):
        value = [value] if value not in (None, "") else []
    out = []
    for v in value:
        n = _num(v)
        if n is not None and int(n) == n and int(n) >= 1 and int(n) not in out:
            out.append(int(n))
    return out


def normalize_beats(raw_beats, duration: float, line_count: int, fallback_camera: str = "", lines=None) -> list:
    """段内小镜头：按起点排序、首尾贴齐 0 和段时长、前后衔接；模型没给小镜头就返回空列表，不补造。"""
    beats = []
    for b in raw_beats or []:
        if not isinstance(b, dict):
            continue
        beats.append({
            "start": _num(b.get("start")),
            "end": _num(b.get("end")),
            "shot_size": str(b.get("shot_size") or "").strip(),
            "camera": str(b.get("camera") or "").strip(),
            "move": str(b.get("move") or "").strip(),
            "action": str(b.get("action") or "").strip(),
            "expression": str(b.get("expression") or "").strip(),
            "line_refs": [r for r in _refs(b.get("line_refs")) if r <= line_count],
        })
    if not beats:
        return []
    beats.sort(key=lambda b: b["start"] if b["start"] is not None else 1e9)
    # 小镜头与台词共用一套时间：有台词引用且台词已定时，从引用的第一句前 0.2 秒开始；
    # 其余没给时间的均分
    n = len(beats)
    for i, b in enumerate(beats):
        if lines and b["line_refs"] and lines[min(b["line_refs"]) - 1].get("start") is not None:
            b["start"] = max(lines[min(b["line_refs"]) - 1]["start"] - 0.2, 0.0)
        if b["start"] is None:
            b["start"] = duration * i / n
    beats.sort(key=lambda b: b["start"])
    for i, b in enumerate(beats):
        b["start"] = 0.0 if i == 0 else min(max(b["start"], beats[i - 1]["start"]), duration)
    kept = []
    for i, b in enumerate(beats):
        nxt = beats[i + 1]["start"] if i + 1 < n else float(duration)
        b["end"] = nxt
        if b["end"] - b["start"] > 1e-6 or (not kept and i == n - 1):
            kept.append(b)
        elif kept:  # 零长度的小镜头并进前一个的台词引用
            kept[-1]["line_refs"] = sorted(set(kept[-1]["line_refs"] + b["line_refs"]))
    kept[0]["start"] = 0.0
    for i in range(1, len(kept)):
        kept[i]["start"] = kept[i - 1]["end"]
    kept[-1]["end"] = float(duration)
    # 太短（不到 MIN_BEAT_SECONDS）的小镜头并进后一个（最后一个并进前一个），镜头拍不出来
    i = 0
    while len(kept) > 1 and i < len(kept):
        b = kept[i]
        if b["end"] - b["start"] >= MIN_BEAT_SECONDS:
            i += 1
            continue
        if i + 1 < len(kept):
            nxt = kept[i + 1]
            nxt["start"] = b["start"]
            nxt["line_refs"] = sorted(set(b["line_refs"] + nxt["line_refs"]))
        else:
            prv = kept[i - 1]
            prv["end"] = b["end"]
            prv["line_refs"] = sorted(set(prv["line_refs"] + b["line_refs"]))
        kept.pop(i)
    for b in kept:
        b["start"], b["end"] = _r1(b["start"]), _r1(b["end"])
    return kept


def legacy_fields(lines: list) -> dict:
    """兼容旧字段：text = 各句顺序拼接；character_name = 首个画内说话人，没有则旁白。"""
    text = "".join(ln["text"] for ln in lines)
    speaker = next((ln["speaker"] for ln in lines if ln["kind"] == "onscreen"), NARRATOR)
    return {"text": text, "character_name": speaker}


def fill_rate(lines: list, duration) -> float:
    """填充率 = 台词朗读时长 / 段时长（0 到 1，保留两位）。"""
    d = _num(duration) or 0
    if d <= 0 or not lines:
        return 0.0
    total = sum(speech_seconds(ln.get("text") or "") for ln in lines)
    return round(min(total / d, 1.0), 2)


def _fmt_sec(x: float) -> str:
    return str(int(x)) if float(x).is_integer() else f"{x:g}"


MAX_SPEAK_TAG_CHARS = 10   # 表情超过这个长度时，用逗号断开再接“说：”


def speak_tag(speaker: str, beat: dict = None, mood: str = "", others=()) -> str:
    """画内台词的说话提示“人物+情绪说：”。情绪来自该小镜头的表情，没有表情时用段的 mood；都没有就只写“说：”。
    台词原文不动，只改说话提示。例：陈子昂冷笑说：／陆川眼眶泛红却死死咬唇，说：／赵虎压抑地说：／陈子昂（步步紧逼）说：。

    others：本段其他人物名。小镜头拍的是别人的反应（动作里只出现别人、没出现说话人）时，表情不属于说话人，退回 mood。"""
    beat = beat or {}
    expr = str(beat.get("expression") or "").strip().rstrip("，,。；;")
    action = str(beat.get("action") or "")
    if expr and speaker not in action and any(o and o != speaker and o in action for o in others):
        expr = ""
    if expr:
        return f"{speaker}{expr}说：" if len(expr) <= MAX_SPEAK_TAG_CHARS else f"{speaker}{expr}，说："
    m = str(mood or "").strip().rstrip("，,。；;")
    if m:
        return f"{speaker}{m}地说：" if len(m) <= 2 else f"{speaker}（{m}）说："  # 四字短语接“地说”不通顺
    return f"{speaker}说："


def beat_of_line(beats: list, line_no: int) -> dict:
    """引用了第 line_no 句台词的小镜头（没有返回空 dict）。"""
    for b in beats or []:
        if isinstance(b, dict) and line_no in (b.get("line_refs") or []):
            return b
    return {}


MAJOR_SHOT_SIZES = ("特写", "近景", "中近景")   # 以这些为主，中景、远景为辅
SAME_SIZE_RUN = 3                              # 连续这么多个小镜头同一景别就告警


def shot_size_warnings(segments: list) -> list:
    """景别自检：按播放顺序连起所有小镜头，连续 3 个同一景别就提示一次（跨段也算）。

    segments 是段列表（每段有 beats）；返回说明列表，供 notes / warnings 使用。
    """
    run_size, run_len, run_from = None, 0, None
    out = []
    for si, seg in enumerate(segments):
        if not isinstance(seg, dict):
            continue
        seg_label = seg.get("shot_no") or seg.get("segment_no") or si + 1
        for bi, b in enumerate(seg.get("beats") or []):
            size = re.sub(r"\s+", "", str((b or {}).get("shot_size") or "")) if isinstance(b, dict) else ""
            if size and size == run_size:
                run_len += 1
            else:
                run_size, run_len, run_from = size, 1, (seg_label, bi + 1)
            if size and run_len == SAME_SIZE_RUN:
                out.append(f"从段 {run_from[0]} 第 {run_from[1]} 个小镜头起连续 {SAME_SIZE_RUN} 个小镜头都是{size}，"
                           f"景别要有变化（以特写、近景、中近景为主，中景、远景为辅）")
    return out


def _sentences(text: str, capacity: float) -> list:
    """切成句子；单句仍超过 capacity 的再按逗号、最后按字数切。"""
    out = []
    for p in [x for x in _SENTENCE_END.split(text) if x.strip()] or [text]:
        out.extend(_split_text(p, capacity) if speech_seconds(p) > capacity else [p])
    return out


def segment_capacity(model: dict) -> float:
    """台词预算：一段最多装多少秒朗读（纯朗读，不含句间留白），超过就要拆段。15 秒段约 58 字。"""
    return float(model["max_duration"]) - SPEECH_MARGIN


def speech_total(lines: list) -> float:
    """段内纯朗读秒数（不含句间留白），台词预算按它算。"""
    return sum(speech_seconds(ln["text"]) for ln in lines)


def _partition(items: list, capacity: float) -> list:
    """items = [(来源, line)]，按顺序分成最少的组（每组朗读 ≤ capacity），并让各组尽量一样长。返回 [(a, b)] 区间。"""
    n = len(items)
    if n == 0:
        return []

    def cost(a, b):
        return speech_total([x[1] for x in items[a:b]])

    k, cur = 1, 0
    for i in range(1, n + 1):
        if cost(cur, i) > capacity and i - 1 > cur:
            k, cur = k + 1, i - 1
    INF = float("inf")
    best = [[INF] * (n + 1) for _ in range(k + 1)]
    cut = [[0] * (n + 1) for _ in range(k + 1)]
    best[0][0] = 0.0
    for g in range(1, k + 1):
        for b in range(1, n + 1):
            for a in range(g - 1, b):
                if best[g - 1][a] == INF:
                    continue
                c = cost(a, b)
                if c > capacity and b - a > 1:
                    continue
                v = max(best[g - 1][a], c)
                if v < best[g][b] - 1e-9:
                    best[g][b], cut[g][b] = v, a
    bounds, b = [], n
    for g in range(k, 0, -1):
        a = cut[g][b]
        bounds.append((a, b))
        b = a
    return list(reversed(bounds))


FINE_PIECE_SECONDS = 4.0  # 重新装段时，长于这个秒数的句子再按逗号切细，装得更满


def _fine_pieces(text: str, capacity: float) -> list:
    """句子粒度；长句再按逗号切（标点处拆到相邻两段是允许的）。"""
    out = []
    for p in _sentences(text, capacity):
        if speech_seconds(p) > FINE_PIECE_SECONDS:
            parts = [x for x in _CLAUSE_END.split(p) if x.strip()]
            out.extend(parts if len(parts) > 1 else [p])
        else:
            out.append(p)
    return out


def _chunk_lines(lines: list, capacity: float) -> list:
    """把一段的 lines 分成若干组，每组朗读总时长（含句间留白）不超过 capacity。

    装得下就整组返回；装不下时先把每句切到句子粒度，再用最少的组数做连续划分并让各组尽量一样长
    （避免拆出一段很满、一段很空），同一原句在组内的相邻碎片再拼回一句。
    """
    if speech_total(lines) <= capacity:
        return [[(i, ln) for i, ln in enumerate(lines)]]
    items = []
    for idx, ln in enumerate(lines):
        for k, p in enumerate(_sentences(ln["text"], capacity)):
            items.append((idx, dict(ln, text=p, start=ln["start"] if k == 0 else None, end=None)))
    groups = []
    for a, b in _partition(items, capacity):
        merged = []
        for idx, ln in items[a:b]:
            if merged and merged[-1][0] == idx:
                merged[-1] = (idx, dict(merged[-1][1], text=merged[-1][1]["text"] + ln["text"]))
            else:
                merged.append((idx, ln))
        groups.append(merged)
    return groups


def scene_key(item: dict) -> str:
    """判断相邻段是不是同一场景：有剧本场次号（scene_no）时按场次号，否则按场景名（scene 字段第一个逗号前）。"""
    no = item.get("scene_no")
    if no not in (None, "") and str(no).strip().isdigit():
        return f"场次{int(str(no).strip())}"
    return re.split(r"[，,。；;]", str(item.get("scene") or ""), maxsplit=1)[0].strip()


def rebalance_segments(items: list, model: dict) -> tuple:
    """同一场景内相邻视频段的台词重新装段（代码兜底）。

    模型常把台词装得不均（一段 7 秒、下一段 16 秒）。同场景连续的若干段里，只要能用更少的段装下、
    或有段装超了，就把这几段的台词按顺序重新分成最少的段、各段尽量一样长；台词集合没变的段原样保留，
    变了的段按小镜头和台词重写视频提示词（角色、场景描述沿用模型原文）。返回 (段列表, 说明列表)。
    """
    capacity = segment_capacity(model)
    out, notes = [], []
    i = 0
    while i < len(items):
        j = i + 1
        key = scene_key(items[i])
        while j < len(items) and key and scene_key(items[j]) == key:
            j += 1
        run = items[i:j]
        i = j
        if len(run) < 2:
            out.extend(run)
            continue
        # 切到句子粒度再装，装完同一原句的相邻碎片拼回去（整句太长时也能装满）
        flat = []
        for si, it in enumerate(run):
            for li, ln in enumerate(normalize_lines(it.get("lines"))):
                for piece in _fine_pieces(ln["text"], capacity):
                    flat.append(((si, li), dict(ln, text=piece, start=None, end=None)))
        totals = [speech_total(normalize_lines(it.get("lines"))) for it in run]
        bounds = _partition(flat, capacity)
        if len(bounds) >= len(run) and max(totals) <= capacity:
            out.extend(run)
            continue
        notes.append(f"同场景「{key}」{len(run)} 段（朗读 {', '.join(f'{t:.1f}' for t in totals)} 秒）"
                     f"重新装成 {len(bounds)} 段")
        for a, b in bounds:
            group = []
            for src, ln in flat[a:b]:
                if group and group[-1][0] == src:
                    group[-1] = (src, dict(group[-1][1], text=group[-1][1]["text"] + ln["text"]))
                else:
                    group.append((src, ln))
            srcs = sorted({src[0] for src, _ in group})
            base = run[srcs[0]]
            orig = normalize_lines(base.get("lines"))
            same = len(srcs) == 1 and [ln["text"] for _, ln in group] == [ln["text"] for ln in orig]
            if same:
                out.append(base)
                continue
            remap = {}
            for n, (src, _) in enumerate(group, start=1):
                remap.setdefault(src, n)
            beats = []
            for si in srcs:
                for bt in run[si].get("beats") or []:
                    if not isinstance(bt, dict):
                        continue
                    orig_refs = _refs(bt.get("line_refs"))
                    # 小镜头跟着它的第一句台词走：第一句不在本段的，整个小镜头不带过来
                    if not orig_refs or (si, orig_refs[0] - 1) not in remap:
                        continue
                    refs = [remap[(si, r - 1)] for r in orig_refs if (si, r - 1) in remap]
                    if refs:
                        beats.append(dict(bt, line_refs=refs, start=None, end=None))
            beats.sort(key=lambda bt: min(bt["line_refs"]))
            chars, props = [], []
            for si in srcs:
                for name in run[si].get("characters") or []:
                    if name not in chars:
                        chars.append(name)
                for name in run[si].get("props") or []:
                    if name not in props:
                        props.append(name)
            last = run[srcs[-1]]
            seg = dict(base, lines=[ln for _, ln in group], beats=beats,
                       characters=chars, props=props, tail=last.get("tail") or base.get("tail"),
                       duration=None, rebalanced=True)
            out.append(seg)
    return out, notes


def normalize_segment(raw: dict, model: dict) -> tuple:
    """校正一条视频段：规整 lines、定段时长、校正每句起止、规整小镜头；朗读装不下时在句子边界拆成多段。

    返回 (段列表, 说明列表)。说明列表非空表示做了代码兜底拆段，调用方记日志。
    """
    notes = []
    lines = normalize_lines(raw.get("lines"))
    capacity = segment_capacity(model)
    groups = _chunk_lines(lines, capacity) if lines else [[]]
    out = []
    if len(groups) > 1:
        notes.append(f"段 {raw.get('segment_no') or raw.get('shot_no') or '?'} 朗读 "
                     f"{speech_total(lines):.1f} 秒超出台词预算 {capacity:g} 秒，按句子边界拆成 {len(groups)} 段")
    for gi, group in enumerate(groups):
        seg_lines = [x[1] for x in group]
        orig_idx = [x[0] for x in group]  # 原 lines 下标（0 起）
        seg = dict(raw)
        seg["lines"] = seg_lines
        split = len(groups) > 1
        dur = _pick_duration(None if split else raw.get("duration"), seg_lines, model)
        if split:
            for ln in seg_lines:
                ln["start"] = None  # 原起点属于整段，拆开后重新排
        time_lines(seg_lines, dur)
        seg["duration"] = dur
        raw_beats = raw.get("beats") or []
        if split:
            # 只保留引用到本组台词的小镜头，台词序号换成本段内序号；时间按本段重排
            remap = {}
            for new_i, oi in enumerate(orig_idx, start=1):
                remap.setdefault(oi + 1, new_i)
            kept = []
            for b in raw_beats:
                if not isinstance(b, dict):
                    continue
                refs = [remap[r] for r in _refs(b.get("line_refs")) if r in remap]
                if refs:
                    kept.append(dict(b, line_refs=refs, start=None, end=None))
            raw_beats = kept
        seg["beats"] = normalize_beats(raw_beats, dur, len(seg_lines), str(raw.get("camera") or ""), seg_lines)
        if split:
            if gi > 0:
                seg["continuity"] = "承接上一段：动作与情绪延续"
                seg["image_prompt"] = raw.get("image_prompt") or raw.get("prompt") or ""
            seg["split_by_code"] = True
        # 画面描述只保留 AI 原文；缺失就留空并记告警，后端不按 beats/场景反拼一段画面。
        if not str(seg.get("video_prompt") or "").strip():
            notes.append(f"段 {seg.get('shot_no') or seg.get('segment_no') or '?'} 缺少 AI 画面描述（video_prompt 为空），未自动生成，请重拆或手动补画面")
        seg["fill_rate"] = fill_rate(seg_lines, dur)
        out.append(seg)
    return out, notes


def retime_segment(seg: dict, model: dict) -> dict:
    """手工改台词后重新校正：不拆段，段时长不变（不短于朗读所需、不超模型上限）。返回要更新的字段。"""
    lines = normalize_lines(seg.get("lines"))
    dur = _num(seg.get("duration")) or model["max_duration"]
    need = _needed_duration(lines)
    dur = float(min(max(dur, need, model["min_duration"]), model["max_duration"]))
    overflow = time_lines(lines, dur)
    fields = {"lines": lines, "duration": dur, "fill_rate": fill_rate(lines, dur), **legacy_fields(lines)}
    if seg.get("beats"):
        fields["beats"] = normalize_beats(seg["beats"], dur, len(lines), lines=lines)
    fields["overflow"] = overflow
    return fields


def _sourced(text: str, flat_novel: str, strict: bool = False) -> bool:
    """台词能否在原文里找到：宽松 = 句首或句尾 6 个字在原文里；严格 = 句首和句尾都在。"""
    t = _NON_SPOKEN.sub("", text or "")
    if not t:
        return False
    head, tail = t[:6] in flat_novel, t[-6:] in flat_novel
    return (head and tail) if strict else (head or tail)


def trim_invented_tail(items: list, novel_text: str) -> tuple:
    """去掉模型在原文讲完之后续写的台词（最后一句能在原文里找到的台词之后、原文里找不到的句子），
    以及紧挨着重复的同一句（模型跨段重复）。删空的段整段去掉。返回 (段列表, 说明列表)。

    只删“原文结束之后”的编造：中间被合规改写过的句子找不到原文也不删，只由 unsourced_lines 报告；
    要删的超过三分之一时不删（原文和台词口径对不上，删了会误伤）。
    """
    flat = _NON_SPOKEN.sub("", novel_text or "")
    if not flat:
        return items, []
    order = [(si, li, ln) for si, it in enumerate(items) for li, ln in enumerate(normalize_lines(it.get("lines")))]
    # 原文最后一句出现的位置：用严格匹配，避免“赵一帆叹了口气，将表收了起来”这种借原文开头编的句子
    last_ok = max((k for k, (_, _, ln) in enumerate(order) if _sourced(ln["text"], flat, strict=True)), default=-1)
    tail_invented = [k for k in range(last_ok + 1, len(order)) if not _sourced(order[k][2]["text"], flat, strict=True)]
    # 保护：一句都对不上原文、或要删的超过三分之一时，多半是传入的原文和台词口径不一致（如润色稿），不删只报告
    allow_trim = last_ok >= 0 and len(tail_invented) <= len(order) / 3
    drop, notes, prev = set(), [], None
    for k, (si, li, ln) in enumerate(order):
        if allow_trim and k > last_ok and not _sourced(ln["text"], flat, strict=True):
            drop.add((si, li))
            notes.append(f"原文结束后模型续写的台词已删除：{ln['text']}")
        elif prev is not None and _NON_SPOKEN.sub("", ln["text"]) == _NON_SPOKEN.sub("", prev):
            drop.add((si, li))
            notes.append(f"重复的台词已删除：{ln['text']}")
        if (si, li) not in drop:
            prev = ln["text"]
    if not drop:
        return items, []
    out = []
    for si, it in enumerate(items):
        lines = normalize_lines(it.get("lines"))
        kept_idx = [li for li in range(len(lines)) if (si, li) not in drop]
        if not kept_idx and lines:
            continue  # 整段都是编的
        if len(kept_idx) == len(lines):
            out.append(it)
            continue
        remap = {li + 1: n for n, li in enumerate(kept_idx, start=1)}
        beats = []
        for b in it.get("beats") or []:
            if isinstance(b, dict):
                refs = [remap[r] for r in _refs(b.get("line_refs")) if r in remap]
                if refs or not b.get("line_refs"):
                    beats.append(dict(b, line_refs=refs))
        out.append(dict(it, lines=[lines[li] for li in kept_idx], beats=beats, rebalanced=True))
    return out, notes


def unsourced_lines(segments: list, novel_text: str) -> list:
    """找出原文里没有的台词（模型自己编的补白）：按去标点后的前 6 个字在原文里查。只报告，不删除
    （合规改写会改动原文字词，自动删除容易误伤）。"""
    flat = _NON_SPOKEN.sub("", novel_text or "")
    out = []
    for seg in segments:
        for ln in seg.get("lines") or []:
            t = _NON_SPOKEN.sub("", ln.get("text") or "")
            if t and t[:6] not in flat and t[-6:] not in flat:
                out.append(ln.get("text"))
    return out
