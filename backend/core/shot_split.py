"""拆分镜：长文分块、紧凑输出展开、跨块合并、截断后缩块重试、进度登记。

模型输出（SHOT_SPLIT_PROMPT）每段只有 scene / pos / mood / sound / lines / beats：
- lines：["旁白：……", "陆川：……", "陆川（心声）：……", "陆川（画外）：……"]
- beats：["中景|平视|缓慢推近|陆川指腹转着杯壁|1,2", ...]
其余字段由这里补齐（expand_segment），再交给 core.shot_timing 统一校正时长、起止和画面描述。
用户自定义的旧模板（lines/beats 为对象、自带 video_prompt）原样兼容。

长文按段落/场景切成不超过 chunk_chars 字的块（split_novel_chunks，不在句中切、不在引号里切），
逐块串行调用（智谱免费模型有 429），把上一块最后一段的场景与尾态传给下一块；合并后统一编号。
某块输出被截断（finish_reason=length）时，把这块对半再切一次重试；仍截断抛 ShotSplitTruncated。
"""
import logging
import math
import re
import time
from typing import Awaitable, Callable, Dict, List, Optional, Tuple

from core.providers.llm_provider import LLMTruncatedError
from core.shot_timing import NARRATOR, trim_invented_tail

logger = logging.getLogger(__name__)

DEFAULT_CHUNK_CHARS = 1500
MAX_SPLIT_CHARS = 20000          # 一次拆分镜最多处理的小说字数（约 14 块），再长请分集拆
# 每块的输出上限（tokens）：正常输出约为小说字数的 2～3 倍字符（≈1.5～2.5 倍 tokens），给到 4 倍留足余量；
# 模型复读跑飞时几十秒就截断，不用等满 16384 tokens（约 5 分钟）
OUTPUT_TOKENS_PER_CHAR = 4
MIN_OUTPUT_TOKENS = 4096
DEFAULT_NEG_PROMPT = "文字，水印，字幕，肢体畸形，面部崩坏"
TRUNCATED_MESSAGE = "小说片段过长，模型输出被截断，请缩短或换模型"


class ShotSplitTruncated(Exception):
    """对半缩块后模型输出仍被截断。"""


# ============================================================
# 分块
# ============================================================
_SENT_END = re.compile(r"[。！？!?…；;]+[”’」』\"']*|\n+")
_OPEN_Q, _CLOSE_Q = "“「『", "”」』"
# 新场景/时间跳转的句首提示词：块尽量从这里切开
_SCENE_CUE = re.compile(
    r"^\s*(那一晚之后|那天之后|从那以后|第二天|次日|翌日|隔天|当晚|当天|那晚|深夜|半夜|凌晨|清晨|一早|傍晚|黄昏|入夜|"
    r"与此同时|另一边|另一头|片刻后|不久后|多年后|几年后|若干年后|"
    r"[一二两三四五六七八九十百几数半\d]+(个)?(秒|分钟|小时|天|日|周|星期|个月|月|年)(后|之后|以后|前|过去了))")


def _boundaries(text: str) -> List[Tuple[int, int]]:
    """候选切点 [(位置, 分数)]：段落换行 3、下一句是场景/时间提示 4、引号外句末 1、引号内句末 0。"""
    out = []
    depth = 0
    pos = 0
    for m in _SENT_END.finditer(text):
        seg = text[pos:m.end()]
        for ch in seg:
            if ch in _OPEN_Q:
                depth += 1
            elif ch in _CLOSE_Q:
                depth = max(depth - 1, 0)
        pos = m.end()
        if pos >= len(text):
            break
        if "\n" in m.group(0):
            score = 3
            depth = 0  # 换行即段落结束，残留的未闭合引号不再影响
        elif depth > 0:
            score = 0
        else:
            score = 1
        if score and _SCENE_CUE.match(text[pos:pos + 20]):
            score = 4
        out.append((pos, score))
    return out


def split_novel_chunks(text: str, max_chars: int = DEFAULT_CHUNK_CHARS) -> List[str]:
    """把小说切成若干块，每块不超过 max_chars 字（单句超长时例外），块长尽量均匀。

    切点优先级：场景/时间切换 > 段落换行 > 引号外的句末；不在句中切，尽量不在引号里切。
    """
    text = (text or "").strip()
    max_chars = max(int(max_chars or DEFAULT_CHUNK_CHARS), 100)
    if len(text) <= max_chars:
        return [text] if text else []
    bounds = _boundaries(text)
    chunks, start = [], 0
    while len(text) - start > max_chars:
        remaining = len(text) - start
        k = math.ceil(remaining / max_chars)
        ideal = start + remaining / k
        limit = start + max_chars
        lo = start + max_chars * 0.5
        cands = [(p, s) for p, s in bounds if start < p <= limit]
        good = [(p, s) for p, s in cands if s > 0]
        pick = None
        if good:
            # 窗口内：分数高优先，同分取离均分点最近的；窗口外（太短）的只在别无选择时用
            win = [(p, s) for p, s in good if p >= lo] or good

            def rank(c):
                p, s = c
                return (min(s, 3) if s < 4 else 4) * max_chars - abs(p - ideal) * (2 if s == 1 else 1)
            pick = max(win, key=rank)[0]
        elif cands:
            pick = max(p for p, _ in cands)  # 只能在引号里的句末切
        else:
            pick = limit  # 一整句超长：硬切
        chunks.append(text[start:pick].strip())
        start = pick
    tail = text[start:].strip()
    if tail:
        chunks.append(tail)
    return [c for c in chunks if c]


def split_in_half(text: str) -> List[str]:
    """截断后缩块：在中点附近的切点把一块切成两半（场景/段落切点优先，其次引号外句末）。切不开返回原块。"""
    text = (text or "").strip()
    bounds = [(p, s) for p, s in _boundaries(text) if 0 < p < len(text)]
    if not bounds:
        return [text] if text else []
    mid = len(text) / 2
    good = [(p, s) for p, s in bounds if s > 0] or bounds
    near = [(p, s) for p, s in good if abs(p - mid) <= len(text) * 0.15] or good
    pick = max(near, key=lambda c: (min(c[1], 4), -abs(c[0] - mid)))[0] if any(s > 1 for _, s in near) \
        else min(near, key=lambda c: abs(c[0] - mid))[0]
    return [x for x in (text[:pick].strip(), text[pick:].strip()) if x]


def chunk_note(index: int, total: int, prev: Optional[dict] = None, more: Optional[bool] = None) -> str:
    """分块说明（注入模板 {chunk_note}）：单块为空。more：本块后面是否还有内容（默认按块序号判断）。"""
    if total <= 1 and not prev and not more:
        return ""
    parts = [f"【分块说明】全文较长，分 {total} 块依次拆，这是第 {index} 块，只拆下面这段【小说段落】。"]
    if prev:
        bits = []
        if prev.get("scene"):
            bits.append(f"场景是“{prev['scene']}”")
        if prev.get("tail"):
            bits.append(f"尾态是“{prev['tail']}”")
        if bits:
            parts.append("上一块最后一段的" + "，".join(bits) + "；本块开头如果还在同一场景，第一段从这个尾态接着拍，不要重复上一块的内容。")
    if (index < total) if more is None else more:
        parts.append("本块之后还有内容，结尾不要收束或总结。")
    return "".join(parts)


# ============================================================
# 紧凑输出 → 完整段字段
# ============================================================
_LINE_HEAD = re.compile(r"^\s*([^：:\n]{1,12}?)\s*(?:[（(]\s*([^）)]{1,4})\s*[）)])?\s*[：:]\s*(.+)$", re.S)
_INNER = ("心声", "内心", "心想", "OS", "os", "独白")
_OFF = ("画外", "画外音", "旁听", "电话")
_REFS_ONLY = re.compile(r"^[\d\s,，、;；]*$")


def parse_line(raw) -> Optional[dict]:
    """“说话人（心声/画外）：原文” → {speaker, text, kind}；对象原样返回。"""
    if isinstance(raw, dict) or raw is None:
        return raw
    s = str(raw).strip()
    if not s:
        return None
    m = _LINE_HEAD.match(s)
    if not m:
        return {"speaker": NARRATOR, "text": s, "kind": "narration"}
    speaker, tag, text = m.group(1).strip(), (m.group(2) or "").strip(), m.group(3).strip()
    if speaker in (NARRATOR, "旁白音", "解说"):
        return {"speaker": NARRATOR, "text": text, "kind": "narration"}
    if tag in _INNER:
        kind = "inner"
    elif tag in _OFF:
        kind = "offscreen"
    else:
        kind = "onscreen"
    return {"speaker": speaker, "text": text, "kind": kind}


def parse_beat(raw) -> Optional[dict]:
    """“景别|机位|运镜|动作|台词序号” → beat 对象（起止由 shot_timing 按台词时间定）；对象原样返回。"""
    if isinstance(raw, dict) or raw is None:
        return raw
    parts = [p.strip() for p in re.split(r"[|｜]", str(raw))]
    refs = []
    if len(parts) > 1 and _REFS_ONLY.match(parts[-1]):
        refs = [int(x) for x in re.findall(r"\d+", parts[-1])]
        parts = parts[:-1]
    shot_size = camera = move = action = ""
    if len(parts) >= 4:
        shot_size, camera, move, action = parts[0], parts[1], parts[2], "，".join(p for p in parts[3:] if p)
    elif len(parts) == 3:
        shot_size, camera, action = parts
    elif len(parts) == 2:
        shot_size, action = parts
    elif parts:
        action = parts[0]
    return {"shot_size": shot_size, "camera": camera, "move": move, "action": action, "line_refs": refs}


def _names_in(text: str, names: set) -> list:
    hits = [(text.find(n), n) for n in names if n and n in text]
    return [n for _, n in sorted(hits)]


def _compose_image_prompt(seg: dict) -> str:
    """段首帧的单帧画面描述：场景 + 站位 + 第一个小镜头的景别与动作（不含台词和声音）。"""
    first = (seg.get("beats") or [{}])[0] if seg.get("beats") else {}
    if not isinstance(first, dict):
        first = {}
    shot = "，".join(x for x in (first.get("shot_size"), first.get("camera")) if x)
    bits = [seg.get("scene"), seg.get("positions"), shot, first.get("action")]
    return "；".join(str(b) for b in bits if b)[:120]


def expand_segment(item: dict, char_names: set = frozenset(), prop_names: set = frozenset()) -> dict:
    """模型的一段（紧凑格式或旧对象格式）→ shot_timing 认得的完整段字段。

    代码补齐：positions（pos）、lines/beats 对象、tail（最后一个小镜头的动作）、characters / props
    （按资产名在台词说话人、站位、动作、台词里出现的先后匹配）、image_prompt、neg_prompt 默认值。
    """
    if not isinstance(item, dict):
        return item
    seg = dict(item)
    if "pos" in seg and not seg.get("positions"):
        seg["positions"] = seg.pop("pos")
    lines = [x for x in (parse_line(ln) for ln in (seg.get("lines") or [])) if x]
    beats = [x for x in (parse_beat(b) for b in (seg.get("beats") or [])) if x]
    seg["lines"], seg["beats"] = lines, beats
    if not seg.get("tail") and beats and isinstance(beats[-1], dict):
        seg["tail"] = beats[-1].get("action") or ""
    speakers = [ln.get("speaker") for ln in lines if isinstance(ln, dict) and ln.get("speaker") not in (None, "", NARRATOR)]
    actions = "；".join(str(b.get("action") or "") for b in beats if isinstance(b, dict))
    spoken = "".join(str(ln.get("text") or "") for ln in lines if isinstance(ln, dict))
    if not seg.get("characters"):
        if char_names:
            seen = _names_in(" ".join(speakers) + "；" + str(seg.get("positions") or "") + "；" + actions + "；" + spoken,
                             set(char_names))
            seg["characters"] = [n for n in dict.fromkeys(
                [s for s in speakers if s in char_names] + seen)]
        else:
            seg["characters"] = list(dict.fromkeys(speakers))
    if not seg.get("props") and prop_names:
        seg["props"] = _names_in(actions + "；" + str(seg.get("positions") or "") + "；" + spoken, set(prop_names))
    if not (seg.get("image_prompt") or seg.get("prompt")):
        seg["image_prompt"] = _compose_image_prompt(seg)
    if not seg.get("neg_prompt"):
        seg["neg_prompt"] = DEFAULT_NEG_PROMPT
    return seg


def link_continuity(items: List[dict]) -> List[dict]:
    """承接：第一段“开场”，其余没写的取上一段的尾态。"""
    prev_tail = None
    for i, it in enumerate(items):
        if not isinstance(it, dict):
            continue
        if not str(it.get("continuity") or "").strip():
            it["continuity"] = "开场" if i == 0 or not prev_tail else f"承接上一段：{prev_tail}"
        prev_tail = it.get("tail") or prev_tail
    return items


# ============================================================
# 逐块调用
# ============================================================
RenderFn = Callable[[str, str], str]                 # (本块小说, 分块说明) → 完整提示词
ProgressFn = Callable[[int, int], None]              # (第几块, 共几块)


def output_tokens(text: str) -> int:
    return max(MIN_OUTPUT_TOKENS, len(text) * OUTPUT_TOKENS_PER_CHAR)


def _items_of(result) -> list:
    if not isinstance(result, dict):
        return []
    items = result.get("segments") or result.get("shots") or []
    return [x for x in items if isinstance(x, dict)]


async def split_in_chunks(llm, novel: str, render: RenderFn, chunk_chars: int = DEFAULT_CHUNK_CHARS,
                          on_progress: Optional[ProgressFn] = None,
                          char_names: set = frozenset(), prop_names: set = frozenset()) -> Tuple[list, dict]:
    """分块拆分镜，返回 (合并后的段列表, 统计)。视频段已展开成完整字段（承接在重新装段后由 link_continuity 补）；
    旧格式（shots）原样返回。

    统计：{"chunks": 块数, "calls": [{chunk, chars, segments, seconds, retried}], "notes": [...]}。
    """
    chunks = split_novel_chunks(novel, chunk_chars)
    total = len(chunks)
    stats: Dict = {"chunks": total, "calls": [], "notes": []}
    merged: list = []
    logger.info(f"[分镜] 小说 {len(novel)} 字，分 {total} 块（每块≤{chunk_chars} 字）：{[len(c) for c in chunks]}")

    async def call(text: str, index: int, label: str, more: Optional[bool] = None) -> list:
        prev = merged[-1] if merged else None
        prompt = render(text, chunk_note(index, max(total, 2) if prev or more else total, prev, more))
        t0 = time.monotonic()
        result = await llm.chat_json([{"role": "user", "content": prompt}], max_tokens=output_tokens(text))
        items = _items_of(result)
        is_seg = any(isinstance(x, dict) and (x.get("lines") or x.get("beats")) for x in items)
        if is_seg:
            items = [expand_segment(x, char_names, prop_names) for x in items]
            items, notes = trim_invented_tail(items, text)
            stats["notes"].extend(notes)
        stats["calls"].append({"chunk": label, "novel_chars": len(text), "segments": len(items),
                               "seconds": round(time.monotonic() - t0, 1)})
        logger.info(f"[分镜] 第 {label} 块（{len(text)} 字）返回 {len(items)} 段，用时 {time.monotonic() - t0:.0f}s")
        return items

    for i, text in enumerate(chunks, start=1):
        if on_progress:
            on_progress(i, total)
        try:
            merged.extend(await call(text, i, f"{i}/{total}"))
        except LLMTruncatedError as e:
            halves = split_in_half(text)
            logger.warning(f"[分镜] 第 {i}/{total} 块（{len(text)} 字）输出被截断（{e.chars} 字符），"
                           f"对半切成 {[len(h) for h in halves]} 字重试一次")
            stats["notes"].append(f"第 {i} 块模型输出被截断，已对半切开重拆")
            if len(halves) < 2:
                raise ShotSplitTruncated(TRUNCATED_MESSAGE) from e
            for j, half in enumerate(halves, start=1):
                try:
                    # 半块沿用整块的序号，分块说明里按“第 i 块”描述，尾态照样接上
                    merged.extend(await call(half, i, f"{i}.{j}/{total}", more=(j < len(halves) or i < total)))
                except LLMTruncatedError as e2:
                    raise ShotSplitTruncated(TRUNCATED_MESSAGE) from e2
    return merged, stats


# ============================================================
# 进度登记（单进程内存；前端轮询 /api/shots/split/progress）
# ============================================================
_PROGRESS: Dict[Tuple[str, str], dict] = {}


def set_progress(user_id: str, project_id: str, chunk: int, total: int) -> None:
    _PROGRESS[(user_id, project_id)] = {"stage": "splitting", "chunk": chunk, "total": total, "at": time.time()}


def get_progress(user_id: str, project_id: str) -> Optional[dict]:
    p = _PROGRESS.get((user_id, project_id))
    if p and time.time() - p["at"] > 3600:  # 进程异常遗留的旧记录
        _PROGRESS.pop((user_id, project_id), None)
        return None
    return p


def clear_progress(user_id: str, project_id: str) -> None:
    _PROGRESS.pop((user_id, project_id), None)
