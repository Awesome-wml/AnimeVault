"""整集 SRT 字幕构建（ASR 实测优先，脚本台词回退）。

时间轴口径：
- 每条成片在草稿轨道上的固定段长 ``SEG``（取自剪映模板片段 target_timerange.duration，
  15066666us），段偏移按此累加；不能用库内 duration=15.0 或真实成片时长，否则结尾漂移。
- 优先用 shot.asr_lines（离线 ASR 实测的段内起止 + 文本）；缺失 / 识别失败时回退
  shot.lines（脚本预估台词，带说话人 / 类型 / 段内起止）。

文本校对：
- ASR 对仙侠专有名词存在近音误写（如角色名、灵石 / 炼气等），``_proofread`` 为可插拔
  校正钩子；第一版先做角色名等确定词表替换，脚本整段对齐回填作为后续增强。
"""
import difflib
import logging
import re
from typing import List, Dict, Tuple

logger = logging.getLogger(__name__)

# 草稿片段固定段长（秒），与剪映模板 target_timerange.duration 一致
SEG = 15066666 / 1_000_000

# 对齐回填阈值：ASR 整段与脚本整段相似度低于该值，视为配音真的改了词，保留 ASR 不回填
_ALIGN_MIN_RATIO = 0.60
# 有效字符：汉字 / 字母 / 数字，标点空格不参与对齐
_CHAR_RE = re.compile(r"[^\u4e00-\u9fffA-Za-z0-9]")

# 确定词表：常见近音 / 形近错写 -> 正确词（只收专有名词与领域固定词，避免误伤通用词）
_PROOFREAD_MAP: Dict[str, str] = {
    "赵炳乾": "赵丙谦",
    "赵炳谦": "赵丙谦",
    "赵丙乾": "赵丙谦",
}


def _fmt(sec: float) -> str:
    """秒 -> srt 时间戳 HH:MM:SS,mmm。"""
    if sec < 0:
        sec = 0.0
    ms = int(round(sec * 1000))
    h, ms = divmod(ms, 3600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _line_text(line: dict) -> str:
    """脚本台词字幕口径：旁白纯台词，对白 / 心声 / 画外带说话人与类型标记。"""
    speaker = (line.get("speaker") or "").strip()
    text = (line.get("text") or "").strip()
    kind = line.get("kind") or "narration"
    if kind == "narration":
        return text
    if kind == "inner":
        return f"{speaker}（心声）：{text}"
    if kind == "offscreen":
        return f"{speaker}（画外）：{text}"
    return f"{speaker}：{text}"


def _proofread(text: str, shot: dict) -> str:
    """校正 ASR 近音错写。先按确定词表替换；角色名可由项目角色表扩充。"""
    if not text:
        return text
    for wrong, right in _PROOFREAD_MAP.items():
        if wrong in text:
            text = text.replace(wrong, right)
    return text


def _clean_chars(text: str) -> str:
    """去掉标点空格，只保留对齐用有效字符。"""
    return _CHAR_RE.sub("", text or "")


def _align_correct(entries: List[Tuple[float, float, str]],
                   lines: List[dict]) -> List[Tuple[float, float, str]]:
    """用脚本台词对 ASR 条目做字级对齐回填：ASR 定时间与分句，脚本只回填识别错的字。

    - 整段相似度达标才回填；差异过大（配音真改词）则原样保留 ASR。
    - 只覆盖 replace 区段的字符，equal 保留 ASR，insert / delete 不改动 ASR 长度。
    """
    if not entries or not lines:
        return entries

    # 记录每个有效字符归属的条目索引
    char_owner: List[int] = []
    asr_chars: List[str] = []
    for i, (_, _, text) in enumerate(entries):
        for ch in _clean_chars(text):
            char_owner.append(i)
            asr_chars.append(ch)
    A = "".join(asr_chars)
    S = _clean_chars("".join(ln.get("text") or "" for ln in lines))
    if not A or not S:
        return entries

    matcher = difflib.SequenceMatcher(None, A, S)
    if matcher.ratio() < _ALIGN_MIN_RATIO:
        return entries

    corrected = list(A)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag != "replace":
            continue
        sseg = S[j1:j2]
        for k in range(i1, i2):
            off = k - i1
            if off < len(sseg):
                corrected[k] = sseg[off]

    by_entry: Dict[int, List[str]] = {i: [] for i in range(len(entries))}
    for owner, ch in zip(char_owner, corrected):
        by_entry[owner].append(ch)

    out: List[Tuple[float, float, str]] = []
    for i, (st, en, text) in enumerate(entries):
        new_text = "".join(by_entry[i]) or text
        out.append((st, en, new_text))
    return out


def proofread_raw(raw: List[Tuple[float, float, str]],
                  lines: List[dict]) -> List[Tuple[float, float, str]]:
    """现场识别条目校对（导出时按需识别，不依赖落库 asr_lines）。

    Args:
        raw: 片段内 ``(start, end, text)``，秒；start/end 为片段内时间。
        lines: 该分镜脚本台词（``shot.lines``），用于字级对齐回填错字。

    Returns:
        校对后的 ``(start, end, text)``；先确定词表替换，再脚本对齐回填。
    """
    cleaned: List[Tuple[float, float, str]] = []
    for st, en, text in raw:
        text = _proofread((text or "").strip(), None)
        if text:
            cleaned.append((st, max(en, st + 0.3), text))
    return _align_correct(cleaned, lines or [])


def _asr_entries(shot: dict, offset: float) -> List[Tuple[float, float, str]]:
    """ASR 实测条目 -> 整集时间轴条目；文本先词表校正，再用脚本对齐回填错字。"""
    raw: List[Tuple[float, float, str]] = []
    for e in shot.get("asr_lines") or []:
        text = _proofread((e.get("text") or "").strip(), shot)
        if not text:
            continue
        st = offset + float(e.get("start") or 0.0)
        en = offset + float(e.get("end") or e.get("start") or 0.0)
        raw.append((st, max(en, st + 0.5), text))
    return _align_correct(raw, shot.get("lines") or [])


def _lines_entries(shot: dict, offset: float) -> List[Tuple[float, float, str]]:
    """脚本台词回退条目，沿用段内起止与零时长兜底。"""
    out: List[Tuple[float, float, str]] = []
    seg_end = offset + SEG
    lines = [ln for ln in (shot.get("lines") or []) if (ln.get("text") or "").strip()]
    for idx, ln in enumerate(lines):
        if ln.get("start") is None or ln.get("end") is None:
            continue
        st = offset + float(ln["start"])
        en = offset + float(ln["end"])
        text = _line_text(ln)
        # 零时长兜底：按 5 字/s 补最小时长，截到段尾 / 下一句起点
        if en <= st:
            dur_line = max(1.2, len(ln.get("text") or "") / 5.0)
            en = min(st + dur_line, seg_end)
            if en <= st:
                st = max(offset, seg_end - dur_line)
                en = seg_end
        nxt = lines[idx + 1] if idx + 1 < len(lines) else None
        if nxt and nxt.get("start") is not None:
            en = min(en, offset + float(nxt["start"]))
        if en > seg_end + 0.05:
            en = seg_end
        if en <= st:
            en = min(st + 1.0, seg_end)
        out.append((st, en, text))
    return out


def build_episode_srt(shots: List[dict], prefer_asr: bool = True) -> str:
    """按整集时间线构建 srt 文本。

    Args:
        shots: 分镜列表（调用方按 shot_no 排序），每条可含 asr_lines / lines。
        prefer_asr: True 时优先 ASR 实测，缺失回退脚本台词。

    Returns:
        srt 文件文本（UTF-8）。
    """
    entries: List[Tuple[float, float, str]] = []
    offset = 0.0
    for shot in shots:
        asr = shot.get("asr_lines") or []
        if prefer_asr and asr:
            entries.extend(_asr_entries(shot, offset))
        else:
            entries.extend(_lines_entries(shot, offset))
        offset += SEG

    entries.sort(key=lambda x: x[0])

    # 相邻条目边界收敛：下一条起点不早于上一条结束，避免轻微重叠；
    # ASR 起点回退 0.15s 会与上一条尾部叠 0.03~0.09s。
    normalized: List[Tuple[float, float, str]] = []
    prev_end = -1.0
    for st, en, text in entries:
        if st < prev_end:
            st = prev_end
        if en <= st:
            en = st + 0.5
        normalized.append((st, en, text))
        prev_end = en

    blocks: List[str] = []
    for i, (st, en, text) in enumerate(normalized, 1):
        blocks.append(str(i))
        blocks.append(f"{_fmt(st)} --> {_fmt(en)}")
        blocks.append(text)
        blocks.append("")
    return "\n".join(blocks)
