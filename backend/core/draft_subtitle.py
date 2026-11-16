"""导出草稿时的字幕轨装配。

导出剪映 / CapCut 草稿前，对该集成片现场离线 ASR 识别，把校对后的字幕条目
（整集全局时间，秒）装配成草稿原生文字轨：

- 文字材料 ``materials.texts[]``：克隆内置基线模板，只替换正文与 id；
- 文字轨 ``tracks[type=text]``：逐条 segment 用 ``material_id`` 关联文字材料，
  ``target_timerange`` 用微秒，``clip.transform`` 沿用基线底部位置；
- 空动画材料 ``materials.material_animations[]``：所有字幕段共享一条。

剪映正文是 ``<font><color><size>`` HTML 标签串；CapCut 正文是
``{"styles":[...], "text": ...}`` JSON 串，两套分别构造。
"""
import copy
import json
import logging
import uuid
from pathlib import Path
from typing import Dict, List, Tuple

logger = logging.getLogger(__name__)

_TPL_DIR = Path(__file__).parent.parent / "bin" / "draft_templates"
_US = 1_000_000


def _load(name: str) -> dict:
    with open(_TPL_DIR / name, encoding="utf-8") as f:
        return json.load(f)


def _new_id() -> str:
    return str(uuid.uuid4()).upper()


def _us(sec: float) -> int:
    return int(round(max(0.0, sec) * _US))


def _esc_html(text: str) -> str:
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _normalize(entries: List[dict]) -> List[dict]:
    """时间兜底：起点不小于 0，时长不小于 0.5s，按起点排序并收敛相邻边界。"""
    out: List[dict] = []
    for e in entries:
        text = (e.get("text") or "").strip()
        if not text:
            continue
        st = float(e.get("start") or 0.0)
        en = float(e.get("end") or st)
        if en <= st:
            en = st + 0.5
        out.append({"text": text, "start": max(0.0, st), "end": en})
    out.sort(key=lambda x: x["start"])

    # 相邻边界收敛：下一条起点不早于上一条结束，消除 ASR 起点回退造成的轻微叠压
    normalized: List[dict] = []
    prev_end = -1.0
    for e in out:
        st, en = e["start"], e["end"]
        if st < prev_end:
            st = prev_end
        if en <= st:
            en = st + 0.5
        normalized.append({"text": e["text"], "start": st, "end": en})
        prev_end = en
    return normalized


def _fill_jianying_content(text: str) -> str:
    return (
        '<font id="" path="">'
        "<color=(1.000000, 1.000000, 1.000000, 1.000000)>"
        f"<size=5.000000>{_esc_html(text)}</size></color></font>"
    )


def _fill_capcut_content(text: str) -> str:
    content = {
        "styles": [
            {
                "fill": {
                    "alpha": 1.0,
                    "content": {
                        "render_type": "solid",
                        "solid": {"alpha": 1.0, "color": [1.0, 1.0, 1.0]},
                    },
                },
                "font": {"id": "", "path": ""},
                "range": [0, len(text)],
                "size": 5.0,
            }
        ],
        "text": text,
    }
    return json.dumps(content, ensure_ascii=False)


def _assemble(platform: str, entries: List[dict]) -> Dict[str, object]:
    tpl_name = "jianying_text.json" if platform == "jianying" else "capcut_text.json"
    tpl = _load(tpl_name)
    entries = _normalize(entries)

    anim = copy.deepcopy(tpl["animations"][0])
    anim["id"] = _new_id()

    texts: List[dict] = []
    segments: List[dict] = []
    for e in entries:
        mid = _new_id()
        seg_id = _new_id()

        mat = copy.deepcopy(tpl["material"])
        mat["id"] = mid
        if platform == "jianying":
            mat["content"] = _fill_jianying_content(e["text"])
        else:
            mat["content"] = _fill_capcut_content(e["text"])
            mat["words"] = {"end_time": [], "start_time": []}
        texts.append(mat)

        seg = copy.deepcopy(tpl["segment"])
        seg["id"] = seg_id
        seg["material_id"] = mid
        seg["extra_material_refs"] = [anim["id"]]
        seg["target_timerange"] = {
            "start": _us(e["start"]),
            "duration": max(1, _us(e["end"] - e["start"])),
        }
        segments.append(seg)

    track = copy.deepcopy(tpl["track_meta"])
    track["id"] = _new_id()
    track["segments"] = segments

    return {"texts": texts, "text_track": track, "animations": [anim]}


def build_jianying(entries: List[dict]) -> Dict[str, object]:
    """装配剪映字幕轨。entries 为整集全局 ``{text, start, end}``（秒）。"""
    return _assemble("jianying", entries)


def build_capcut(entries: List[dict]) -> Dict[str, object]:
    """装配 CapCut 字幕轨。entries 为整集全局 ``{text, start, end}``（秒）。"""
    return _assemble("capcut", entries)


def _lines_fallback(shot: dict) -> List[Tuple[float, float, str]]:
    """脚本台词回退（ASR 失败 / 空结果）：纯台词，段内起止，零时长按 5 字/s 兜底。"""
    out: List[Tuple[float, float, str]] = []
    lines = [ln for ln in (shot.get("lines") or []) if (ln.get("text") or "").strip()]
    for ln in lines:
        st = ln.get("start")
        en = ln.get("end")
        if st is None:
            continue
        if en is None or en <= st:
            en = st + max(1.2, len(ln["text"]) / 5.0)
        out.append((float(st), float(en), ln["text"].strip()))
    return out


def _recognize_one(shot: dict, path: str) -> List[Tuple[float, float, str]]:
    """单条成片识别 + 校对回填，返回片段内 ``(start, end, text)``。"""
    from core.asr_engine import transcribe_video
    from core.subtitle_srt import proofread_raw

    raw: List[Tuple[float, float, str]] = []
    try:
        rec = transcribe_video(path)
        raw = [
            (float(e["start"]), float(e["end"]), e["text"])
            for e in rec if e.get("text")
        ]
    except Exception as exc:  # noqa: BLE001
        logger.warning("导出字幕识别失败 shot=%s: %s", shot.get("shot_no"), exc)
    if not raw:
        raw = _lines_fallback(shot)
    return proofread_raw(raw, shot.get("lines") or [])


def collect_entries(clip_items: List[Tuple[dict, str]], seg_sec: float,
                    workers: int = 10) -> List[dict]:
    """并行识别整集成片，校对回填后映射到整集全局时间。

    Args:
        clip_items: ``[(shot_doc, 成片绝对路径)]``，已按 shot_no 排序。
        seg_sec: 草稿单段固定时长（秒），与视频轨累加口径一致。
        workers: 并行识别线程数；全部识别完成后再返回，顺序与输入一致。

    Returns:
        整集全局 ``[{text, start, end}]``（秒）。ASR 失败的片段回退脚本台词。
    """
    from concurrent.futures import ThreadPoolExecutor

    if not clip_items:
        return []

    workers = max(1, min(workers, len(clip_items)))
    with ThreadPoolExecutor(max_workers=workers) as ex:
        corrected_list = list(ex.map(lambda item: _recognize_one(*item), clip_items))

    entries: List[dict] = []
    cur = 0.0
    for corrected in corrected_list:
        for st, en, text in corrected:
            entries.append({"text": text, "start": cur + st, "end": cur + en})
        cur += seg_sec
    return entries
