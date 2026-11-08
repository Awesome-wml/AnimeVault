"""视频段 → 发给视频模型的完整提示词（五段结构），由代码按实际上传的参考图顺序组装。

【硬性参数】段号、严格时长、画幅、无水印标识
【参考素材】图1..图N 各是谁/什么（只列实际会上传的图，编号 = 上传顺序）
【画面】     模型写的画面时间轴（shots.video_prompt），角色/道具名替换成 名字【@图片N】
【台词与旁白】逐句起止秒；旁白/心声标“画外音，画面人物不张嘴”
【硬性禁区】严格时长不压缩、无水印、无随机字幕、五官服装一致、光影统一、未出场角色不提前出现

编号不交给大模型：模型只写名字，这里按上传顺序替换，避免图号对不上。
旧格式分镜（没有 lines）不经过这里，照旧发 video_prompt 原文。
"""
import re
from pathlib import Path
from typing import Dict, List, Optional

ASPECT = "16:9 横屏"
REF_LABEL = {"分镜参考": "本段首帧画面参考", "角色": "角色", "场景": "场景", "道具": "道具", "关键帧": "上一段尾帧"}
KIND_LABEL = {"narration": "旁白", "inner": "心声", "onscreen": "对白", "offscreen": "画外音"}


def _fmt(x) -> str:
    try:
        f = round(float(x), 1)
    except (TypeError, ValueError):
        return "0"
    return str(int(f)) if f.is_integer() else f"{f:g}"


def collect_refs(shot: dict, chars: list, scenes: list, props: list, static_dir: Path) -> List[Dict]:
    """本段要上传的参考图（按上传顺序）：段首画面 → 出场角色 → 场景 → 道具。只收本地存在的图。

    视频段优先按结构化字段（characters / props / scene）选；旧数据没有这些字段时按名字出现在文本里匹配。
    返回 [{type, name, path}]。
    """
    refs: List[Dict] = []
    seen = set()

    def add(kind, name, rel):
        if not rel:
            return
        f = Path(static_dir) / rel
        if f.exists() and str(f) not in seen:
            seen.add(str(f))
            refs.append({"type": kind, "name": name, "path": str(f)})

    text = " ".join(str(shot.get(k) or "") for k in ("text", "video_prompt", "prompt", "scene"))
    add("分镜参考", "段首画面", shot.get("img_path"))
    want_chars = shot.get("characters") or []
    for ch in chars:
        name = ch.get("name") or ""
        if name and (name in want_chars if want_chars else name in text):
            add("角色", name, ch.get("image_path"))
    scene_text = str(shot.get("scene") or "") or text
    for sc in scenes:
        name = sc.get("name") or ""
        if name and name in scene_text:
            add("场景", name, sc.get("image_path"))
    want_props = shot.get("props") or []
    for pr in props:
        name = pr.get("name") or ""
        if name and (name in want_props if want_props else name in text):
            add("道具", name, pr.get("image_path") or pr.get("img_path"))
    return refs


def filter_refs(refs: List[Dict], model: dict) -> List[Dict]:
    """按模型接受的文件类型过滤（都不接受音频），最多 max_files 个；顺序即上传顺序。"""
    exts = tuple("." + e for e in model.get("reference_types") or ())
    kept = [r for r in refs if r["path"].lower().endswith(exts)]
    return kept[: int(model.get("max_files") or 10)]


def _tag_names(text: str, numbering: Dict[str, int]) -> str:
    """名字 → 名字【@图片N】；长名字先替换，已带标记的不重复替换。"""
    for name in sorted(numbering, key=len, reverse=True):
        text = re.sub(re.escape(name) + r"(?!【@图片)", f"{name}【@图片{numbering[name]}】", text)
    return text


def speaker_warnings(shot: dict, refs: List[Dict]) -> List[str]:
    """有画内台词的角色必须有参考图，否则视频模型不知道谁在说话。"""
    have = {r["name"] for r in refs if r["type"] == "角色"}
    out = []
    for ln in shot.get("lines") or []:
        if ln.get("kind") == "onscreen" and ln.get("speaker") not in have:
            msg = f"{ln.get('speaker')} 有画内台词但没有参考图"
            if msg not in out:
                out.append(msg)
    return out


def assemble_video_prompt(shot: dict, refs: List[Dict], seg_no: Optional[int] = None) -> str:
    """按五段结构组装完整提示词。refs 必须是实际上传的图（顺序 = 上传顺序）。"""
    dur = _fmt(shot.get("duration") or 15)
    no = int(seg_no if seg_no is not None else shot.get("shot_no") or 1)
    hard = f"段号 SEG{no:03d}；严格时长 {dur} 秒，不压缩不加长；{ASPECT}；无水印、无平台标识、无角标、无logo"

    numbering: Dict[str, int] = {}
    ref_lines = []
    for i, r in enumerate(refs, start=1):
        label = REF_LABEL.get(r["type"], r["type"])
        if r["type"] == "角色":
            lines = shot.get("lines") or []
            role = "主讲" if any(ln.get("speaker") == r["name"] and ln.get("kind") == "onscreen" for ln in lines) else "出场"
            ref_lines.append(f"图{i}：{label}{r['name']}（{role}，五官服装以此为准）")
        elif r["type"] == "分镜参考":
            ref_lines.append(f"图{i}：{label}（构图与光影以此为准）")
        else:
            ref_lines.append(f"图{i}：{label}{r['name']}")
        if r["type"] in ("角色", "道具", "场景"):
            numbering.setdefault(r["name"], i)
    refs_txt = "；".join(ref_lines) if ref_lines else "无参考图"

    picture = str(shot.get("video_prompt") or "").strip().rstrip("；;")
    picture = _tag_names(picture, numbering) if numbering else picture

    said = []
    for ln in shot.get("lines") or []:
        t = f"[{_fmt(ln.get('start'))}-{_fmt(ln.get('end'))}秒]"
        text = str(ln.get("text") or "").strip()
        sp = ln.get("speaker") or "旁白"
        if ln.get("kind") == "onscreen":
            said.append(f"{t}{sp}说：{text}（{sp}露脸，口型对上，其他人不开口）")
        elif ln.get("kind") == "offscreen":
            said.append(f"{t}画外传来{sp}的声音：{text}（{sp}不在画面里）")
        else:
            who = "旁白" if ln.get("kind") == "narration" else f"{sp}心声"
            said.append(f"{t}{who}：{text}（画外音，画面人物不张嘴）")
    said_txt = "；".join(said) if said else "本段无台词，画面中人物不开口说话"

    forbid = (f"严格时长 {dur} 秒，不压缩不加长；无水印、无平台标识、无角标、无logo；不生成任何字幕或随机文字；"
              "人物五官、发型、服装与参考图一致，前后不变；光影与色调统一；本段未出场的角色不要提前出现；"
              "只要环境音和动作音，不要背景音乐、贝斯或任何音乐元素")
    return (f"【硬性参数】{hard}\n【参考素材】{refs_txt}\n【画面】{picture}\n"
            f"【台词与旁白】{said_txt}\n【硬性禁区】{forbid}")
