"""剧本场次文本拼接工具。"""
from __future__ import annotations

from typing import List, Dict


NARRATOR = "旁白"
LINE_KINDS = ("narration", "inner", "onscreen", "offscreen")
KIND_TAG = {"inner": "（心声）", "offscreen": "（画外）"}
VOICED_HEAD = "台词："
# 场头里不配音的行（拆分镜只拿来写 beats / scene / pos）
_META_HEADS = ("地点：", "时间：", "出场：", "动作/环境", "节拍", "【场次")


def normalize_kind(speaker: str, kind: str = "") -> tuple:
    """台词类型兜底，返回 (speaker, kind)：旁白一律 narration；kind=narration 但说话人是角色 → 说话人改成旁白；
    缺省或不认识的 kind：旁白 → narration，其余 → onscreen。"""
    speaker = (speaker or "").strip() or NARRATOR
    kind = (kind or "").strip().lower()
    if speaker == NARRATOR:
        return NARRATOR, "narration"
    if kind == "narration":
        return NARRATOR, "narration"
    if kind not in LINE_KINDS:
        kind = "onscreen"
    return speaker, kind


def dialogue_line(d: Dict) -> str:
    """一条台词 → 拆分镜认得的“说话人（心声/画外）：台词”（core.shot_split.parse_line 能解析出 kind）。"""
    speaker, kind = normalize_kind(d.get("speaker"), d.get("kind"))
    line = (d.get("line") or "").strip()
    if kind == "narration":
        return f"{NARRATOR}：{line}"
    return f"{speaker}{KIND_TAG.get(kind, '')}：{line}"


def _scene_head(s: Dict) -> List[str]:
    head = [f"【场次{s.get('scene_no', '')}】"]
    if s.get("location"):
        head.append(f"地点：{s['location']}")
    if s.get("time"):
        head.append(f"时间：{s['time']}")
    chars = [c for c in (s.get("characters") or []) if c]
    if chars:
        head.append(f"出场：{'、'.join(chars)}")
    if s.get("action"):
        head.append(f"动作/环境（不配音）：{s['action']}")
    return head


def scene_text(s: Dict, dialogues=None) -> str:
    """一场剧本的文本：场头（地点/时间/出场/动作，不配音）+“台词：”下逐条台词 + 节拍（不配音）。"""
    lines = _scene_head(s)
    ds = s.get("dialogues") if dialogues is None else dialogues
    lines.append(VOICED_HEAD)
    lines += [dialogue_line(d) for d in (ds or []) if isinstance(d, dict) and (d.get("line") or "").strip()]
    if s.get("beat"):
        lines.append(f"节拍（不配音）：{s['beat']}")
    return "\n".join(lines)


def scripts_to_text(scripts: List[Dict]) -> str:
    """把剧本场次拼成连贯文本，供资产提取 / 分镜拆分使用。"""
    return "\n\n".join(scene_text(s) for s in scripts)


def voiced_text(scripts: List[Dict]) -> str:
    """只含配音台词的纯文本（段数预算、台词溯源用的“原文”）。"""
    return "\n".join((d.get("line") or "").strip() for s in scripts
                     for d in (s.get("dialogues") or []) if isinstance(d, dict) and (d.get("line") or "").strip())


def voiced_of_text(text: str) -> str:
    """从 scripts_to_text 产出的（一块）文本里取出配音台词正文；不是剧本格式时原样返回。"""
    if VOICED_HEAD not in (text or ""):
        return text or ""
    out = []
    for raw in text.split("\n"):
        ln = raw.strip()
        if not ln or ln == VOICED_HEAD or ln.startswith(_META_HEADS):
            continue
        out.append(ln.split("：", 1)[1] if "：" in ln else ln)
    return "\n".join(out)


def chunk_scenes(scripts: List[Dict], max_chars: int = 1500) -> List[str]:
    """剧本按整场打包成块（块边界只落在场次之间），每块不超过 max_chars；
    单场超长时按台词条切开，每片都带完整场头，模型仍知道地点、出场和动作。"""
    max_chars = max(int(max_chars or 1500), 200)
    pieces: List[str] = []
    for s in scripts:
        txt = scene_text(s)
        if len(txt) <= max_chars:
            pieces.append(txt)
            continue
        ds = [d for d in (s.get("dialogues") or []) if isinstance(d, dict) and (d.get("line") or "").strip()]
        base = len(scene_text(s, []))
        part: list = []
        size = base
        for d in ds:
            n = len(dialogue_line(d)) + 1
            if part and size + n > max_chars:
                pieces.append(scene_text(s, part))
                part, size = [], base
            part.append(d)
            size += n
        if part or not ds:
            pieces.append(scene_text(s, part))
    chunks: List[str] = []
    for p in pieces:
        if chunks and len(chunks[-1]) + len(p) + 2 <= max_chars:
            chunks[-1] += "\n\n" + p
        else:
            chunks.append(p)
    return chunks


def halve_scene_chunk(text: str) -> List[str]:
    """剧本块截断后对半切：在中点附近的台词行之间切开，后半块补上所在场次的场头（地点/时间/出场/动作）。"""
    lines = (text or "").split("\n")
    voiced_idx = [i for i, ln in enumerate(lines)
                  if ln.strip() and ln.strip() != VOICED_HEAD and not ln.strip().startswith(_META_HEADS)]
    if len(voiced_idx) < 2:
        return [text] if text else []
    total = len(text)
    acc, cut = 0, voiced_idx[len(voiced_idx) // 2]
    for i, ln in enumerate(lines):
        acc += len(ln) + 1
        if i in voiced_idx and acc >= total / 2 and i != voiced_idx[-1]:
            cut = i + 1
            break
    first, second = lines[:cut], lines[cut:]
    if second and not second[0].startswith("【场次"):
        head_start = max((i for i, ln in enumerate(first) if ln.startswith("【场次")), default=None)
        if head_start is not None:
            head = []
            for ln in first[head_start:]:
                head.append(ln)
                if ln.strip() == VOICED_HEAD:
                    break
            second = head + second
    return [x for x in ("\n".join(first).strip(), "\n".join(second).strip()) if x]


def clean_dialogues(dialogues) -> List[Dict]:
    """规整台词：去空白、丢空台词、kind 兜底（normalize_kind）。"""
    out = []
    for d in (dialogues or []):
        if hasattr(d, "dict"):
            d = d.dict()
        if not isinstance(d, dict):
            continue
        line = str(d.get("line") or "").strip()
        if not line:
            continue
        speaker, kind = normalize_kind(str(d.get("speaker") or ""), str(d.get("kind") or ""))
        out.append({"speaker": speaker, "line": line, "kind": kind})
    return out


def script_chunk_note(index: int, total: int, prev_scene: Dict = None) -> str:
    """长文分块转剧本时的说明（注入 SCRIPT_CONVERT_PROMPT 的 {chunk_note}）；单块为空。"""
    if total <= 1:
        return ""
    parts = [f"【分块说明】小说较长，分 {total} 块依次改编，这是第 {index} 块，只改编下面这段【小说原文】。"]
    if index > 1:
        parts.append("开头钩子只在第 1 块要求，本块直接接着上一块往下写，不要重新开场或重复上一块的内容。")
        if prev_scene:
            loc = prev_scene.get("location") or ""
            tm = prev_scene.get("time") or ""
            chars = "、".join(c for c in (prev_scene.get("characters") or []) if c)
            parts.append(f"上一块最后一场：地点“{loc}”，时间“{tm}”，出场“{chars}”；"
                         "如果本块开头还在同一地点和时间，地点、时间照原样写（系统会接到上一场里），角色名保持一致。")
    if index < total:
        parts.append("本块之后还有内容，结尾不要收束或总结。")
    return "".join(parts)


def _same_place(a: Dict, b: Dict) -> bool:
    la, lb = str(a.get("location") or "").strip(), str(b.get("location") or "").strip()
    return bool(la) and la == lb and str(a.get("time") or "").strip() == str(b.get("time") or "").strip()


def merge_chunk_scenes(chunk_scenes_list: List[List[Dict]]) -> List[Dict]:
    """把逐块转出的场次合并成一部剧本：块与块交界处地点和时间都相同的两场接成一场，最后场次从 1 重新编号。"""
    merged: List[Dict] = []
    for ci, scenes in enumerate(chunk_scenes_list or []):
        for si, sc in enumerate(s for s in (scenes or []) if isinstance(s, dict)):
            sc = dict(sc)
            sc["dialogues"] = clean_dialogues(sc.get("dialogues"))
            sc["characters"] = [str(c).strip() for c in (sc.get("characters") or []) if c and str(c).strip()]
            if ci > 0 and si == 0 and merged and _same_place(merged[-1], sc):
                last = merged[-1]
                last["dialogues"] = last["dialogues"] + sc["dialogues"]
                last["characters"] = list(dict.fromkeys(last["characters"] + sc["characters"]))
                for key in ("action", "beat"):
                    joined = "；".join(x for x in (str(last.get(key) or "").strip(), str(sc.get(key) or "").strip()) if x)
                    last[key] = joined
                continue
            merged.append(sc)
    for i, sc in enumerate(merged, start=1):
        sc["scene_no"] = i
    return merged


async def load_scripts(db, project_id: str) -> List[Dict]:
    """读项目的剧本场次，按场次号排序；没有剧本返回空列表。"""
    if not project_id:
        return []
    rows = await db.scripts.find({"project_id": project_id}).sort("scene_no", 1).to_list(None)
    return rows or []


async def load_script_text(db, project_id: str):
    """(剧本拼接文本, 场次数)；没有剧本返回 ("", 0)，调用方兜底用小说原文。"""
    rows = await load_scripts(db, project_id)
    if not rows:
        return "", 0
    return scripts_to_text(rows), len(rows)


async def scene_location_of(db, shot: Dict) -> str:
    """分镜所属剧本场次的地点（shot.scene_no → scripts.location）；没有场次返回空串。"""
    no = shot.get("scene_no")
    if no is None or not shot.get("project_id"):
        return ""
    row = await db.scripts.find_one({"project_id": shot["project_id"], "scene_no": no}, {"location": 1})
    return (row or {}).get("location") or ""


def locate_scene_no(lines: List[Dict], scripts: List[Dict]):
    """按台词原文在哪个场次里出现，判断视频段属于第几场；找不到返回 None。

    拆分镜按场次分块，一块可能含多场，模型不回填场次号，这里由代码反查。
    """
    def norm(t: str) -> str:
        return "".join(ch for ch in str(t or "") if ch.isalnum())

    blobs = [(s.get("scene_no"), norm(scripts_to_text([s]))) for s in scripts]
    for ln in lines or []:
        t = norm(ln.get("text") if isinstance(ln, dict) else ln)
        if len(t) < 4:
            continue
        probe = t[:12]
        for no, blob in blobs:
            if probe in blob:
                return no
    return None
