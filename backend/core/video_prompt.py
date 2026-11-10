"""视频段 → 发给视频模型的完整提示词，由代码按实际上传的参考图顺序组装。

【硬性参数】段号、严格时长、画幅、无水印标识
【参考素材】图1..图N 各是谁/什么（只列实际会上传的图，编号 = 上传顺序）
【画面】     AI 写好的整段画面描述（shots.video_prompt），角色/道具名替换成 名字【@图片N】
【台词与旁白】逐句起止秒；画内台词写“人物说：台词”（台词原文不动）；旁白/心声标“画外音，画面人物不张嘴”
【硬性禁区】严格时长不压缩、无水印、无随机字幕、五官服装一致、光影统一、未出场角色不提前出现、
            同一镜头同一角色只有一个实体、群演各异

编号不交给大模型：模型只写名字，这里按上传顺序替换，避免图号对不上。
旧格式分镜（没有 lines）不经过这里，照旧发 video_prompt 原文。
"""
import re
from pathlib import Path
from typing import Dict, List, Optional

from core.shot_timing import NARRATOR, shot_size_warnings, speak_tag

ASPECT = "16:9 横屏"
REF_LABEL = {"分镜参考": "本段首帧画面参考", "角色": "角色", "场景": "场景", "道具": "道具", "关键帧": "上一段尾帧"}
# 分镜参考图有两种：四格图（T-215 起，优先）和旧的单张首帧（旧段没有四格图时回退）；ref 的 name 区分
STORYBOARD_NAME, FRAME_NAME = "四格分镜", "段首画面"
STORYBOARD_LABEL = "本段四格分镜（左上→右上→左下→右下 依次对应本段四个时间段，构图、站位与光影以此为准）"
KIND_LABEL = {"narration": "旁白", "inner": "心声", "onscreen": "对白", "offscreen": "画外音"}


def _fmt(x) -> str:
    try:
        f = round(float(x), 1)
    except (TypeError, ValueError):
        return "0"
    return str(int(f)) if f.is_integer() else f"{f:g}"


TYPE_CN = {"character": "角色", "scene": "场景", "prop": "道具"}


def collect_refs(shot: dict, chars: list, scenes: list, props: list, static_dir: Path,
                 scene_location: str = "") -> List[Dict]:
    """本段要上传的参考图（按上传顺序）：分镜参考（四格图，没有则首帧）→ 绑定的资产。只收本地存在的图。

    “用哪些资产、什么顺序”统一由 core.asset_binding.collect_bindings 决定（角色 → 场景 → 道具；
    视频段按结构化字段，旧数据按名字匹配；场次地点参与场景归属）。
    返回 [{type, name, path, label, asset_id}]，type 为中文（分镜参考/角色/场景/道具）。
    """
    from core.asset_binding import collect_bindings

    refs: List[Dict] = []
    seen = set()

    def add(kind, name, rel, label="", asset_id=None, **extra):
        if not rel:
            return
        f = Path(static_dir) / rel
        if f.exists() and str(f) not in seen:
            seen.add(str(f))
            refs.append({"type": kind, "name": name, "path": str(f), "label": label, "asset_id": asset_id, **extra})

    add("分镜参考", STORYBOARD_NAME, shot.get("storyboard_path"))
    if not refs:  # 没有四格图（旧段）才用单张首帧
        add("分镜参考", FRAME_NAME, shot.get("img_path"))
    for b in collect_bindings(shot, chars, scenes, props, scene_location=scene_location):
        extra = {k: b[k] for k in ("form", "warning") if b.get(k)}
        add(TYPE_CN[b["asset_type"]], b["name"], b.get("img"), b.get("label") or "", b.get("asset_id"), **extra)
    return refs


def form_warnings(refs: List[Dict]) -> List[str]:
    """角色形态与本段场次对不上时的提示（collect_bindings 已按第一形态兜底）。"""
    return [r["warning"] for r in refs if r.get("warning")]


def filter_refs(refs: List[Dict], model: dict) -> List[Dict]:
    """按模型接受的文件类型过滤（都不接受音频），最多 max_files 个；顺序即上传顺序。"""
    exts = tuple("." + e for e in model.get("reference_types") or ())
    kept = [r for r in refs if r["path"].lower().endswith(exts)]
    return kept[: int(model.get("max_files") or 10)]


_SPOKEN_SPAN = re.compile(r"(说：|的声音：)[^；;]*")


def _tag_names(text: str, numbering: Dict[str, int]) -> str:
    """名字 → 名字【@图片N】；长名字先替换，已带标记的不重复替换；台词（“说：”之后到分号）里的名字不动。"""
    names = sorted(numbering, key=len, reverse=True)
    pattern = re.compile("|".join(re.escape(n) for n in names))

    def tag(chunk: str) -> str:
        return pattern.sub(lambda m: f"{m.group(0)}【@图片{numbering[m.group(0)]}】", chunk) if names else chunk

    out, pos = [], 0
    for m in _SPOKEN_SPAN.finditer(text):
        out.append(tag(text[pos:m.start()]))
        out.append(m.group(0))
        pos = m.end()
    out.append(tag(text[pos:]))
    return "".join(out)


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


def _people(shot: dict) -> List[str]:
    """画面人物：段的 characters，再补有画内台词的说话人；去重保序。"""
    names = [str(n) for n in (shot.get("characters") or []) if n]
    for ln in shot.get("lines") or []:
        sp = ln.get("speaker")
        if ln.get("kind") == "onscreen" and sp and sp != NARRATOR and sp not in names:
            names.append(str(sp))
    return list(dict.fromkeys(names))


_TIME_SPAN = re.compile(r"\[\d+(?:\.\d+)?-\d+(?:\.\d+)?秒\]")


def tag_panels(picture: str, shot: dict) -> str:
    """【画面】里每个小镜头的时间段后面标上四格图里对应的格：[0-4.4秒 S1 左上格]…；
    时间段数与小镜头数对不上（用户手改过画面描述）时只标前面能对上的。"""
    from core.storyboard import panel_tags

    tags = panel_tags(shot)
    if not tags:
        return picture
    it = iter(tags)

    def sub(m):
        tag = next(it, None)
        return m.group(0) if tag is None else m.group(0)[:-1] + f" {tag}]"

    return _TIME_SPAN.sub(sub, picture)


def assemble_video_prompt(shot: dict, refs: List[Dict], seg_no: Optional[int] = None, genre: str = "",
                          style_suffix: str = "") -> str:
    """组装完整提示词：硬性参数 + 参考素材 + 画面（AI 整段直发）+（风格）+ 台词与旁白 + 硬性禁区。
    style_suffix 是项目媒介与题材的视频风格词（style_library.build_video_style_suffix），为空不写【风格】行。
    refs 必须是实际上传的图（顺序 = 上传顺序）；genre 仅保留兼容调用方，画面正文不再由代码按题材反推。
    参考里有四格分镜图时，【画面】各时间段标注对应的格（S1–S4）。"""
    dur = _fmt(shot.get("duration") or 15)
    no = int(seg_no if seg_no is not None else shot.get("shot_no") or 1)
    hard = f"段号 SEG{no:03d}；严格时长 {dur} 秒，不压缩不加长；{ASPECT}；无水印、无平台标识、无角标、无logo"

    numbering: Dict[str, int] = {}
    ref_lines = []
    has_storyboard = False
    for i, r in enumerate(refs, start=1):
        label = REF_LABEL.get(r["type"], r["type"])
        if r["type"] == "角色":
            lines = shot.get("lines") or []
            role = "主讲" if any(ln.get("speaker") == r["name"] and ln.get("kind") == "onscreen" for ln in lines) else "出场"
            form = f"，{r['form']}" if r.get("form") and r["form"] != "单形态" else ""
            ref_lines.append(f"图{i}：{label}{r['name']}（{role}{form}，五官服装以此为准）")
        elif r["type"] == "分镜参考" and r.get("name") == STORYBOARD_NAME:
            has_storyboard = True
            ref_lines.append(f"图{i}：{STORYBOARD_LABEL}")
        elif r["type"] == "分镜参考":
            ref_lines.append(f"图{i}：{label}（构图与光影以此为准）")
        else:
            ref_lines.append(f"图{i}：{label}{r['name']}")
        if r["type"] in ("角色", "道具", "场景"):
            numbering.setdefault(r["name"], i)
    refs_txt = "；".join(ref_lines) if ref_lines else "无参考图"

    picture = str(shot.get("video_prompt") or "").strip().rstrip("；;")
    if not picture:
        # 后端不按场景/台词反拼画面：AI 没给就明确标缺失，避免把空画面当正常提示词发出。
        picture = "（本段缺少 AI 画面描述，未自动生成，请补充画面后再生成）"
    if has_storyboard:
        picture = tag_panels(picture, shot)
    picture = _tag_names(picture, numbering) if numbering else picture

    said = []
    mood = str(shot.get("mood") or "")
    people = _people(shot)
    for i, ln in enumerate(shot.get("lines") or [], start=1):
        t = f"[{_fmt(ln.get('start'))}-{_fmt(ln.get('end'))}秒]"
        text = str(ln.get("text") or "").strip()
        sp = ln.get("speaker") or "旁白"
        if ln.get("kind") == "onscreen":
            said.append(f"{t}{speak_tag(sp, {}, mood, people)}{text}"
                        f"（{sp}露脸，口型对上，其他人不开口）")
        elif ln.get("kind") == "offscreen":
            said.append(f"{t}画外传来{sp}的声音：{text}（{sp}不在画面里）")
        else:
            who = "旁白" if ln.get("kind") == "narration" else f"{sp}心声"
            said.append(f"{t}{who}：{text}（画外音，画面人物不张嘴）")
    said_txt = "；".join(said) if said else "本段无台词，画面中人物不开口说话"

    forbid = (f"严格时长 {dur} 秒，不压缩不加长；无水印、无平台标识、无角标、无logo；不生成任何字幕或随机文字；"
              "人物五官、发型、服装与参考图一致，前后不变；光影与色调统一；本段未出场的角色不要提前出现；"
              "同一镜头中同一角色只能出现一个实体，禁止分身、克隆、镜像重复；群演和路人长相、穿搭各不相同，不复制同一张脸；"
              "只要环境音和动作音，不要背景音乐、贝斯或任何音乐元素")
    style_line = f"【风格】{style_suffix.strip()}\n" if (style_suffix or "").strip() else ""
    return (f"【硬性参数】{hard}\n【参考素材】{refs_txt}\n【画面】{picture}\n{style_line}"
            f"【台词与旁白】{said_txt}\n【硬性禁区】{forbid}")


def build_upload_plan(shot: dict, chars: list, scenes: list, props: list, static_dir: Path,
                      model: dict, scene_location: str = "", seg_no: Optional[int] = None,
                      extra_refs: Optional[List[Dict]] = None, genre: str = "", style_suffix: str = "") -> Dict:
    """一次视频生成的上传计划：参考图文件（顺序 = 上传顺序）与发给模型的提示词，出自同一个 refs 列表。

    返回 {"files": [绝对路径], "refs": [...], "prompt": str, "warnings": [...]}。
    视频段（有 lines）按硬性参数 + 参考素材 + 画面（AI 整段直发）+ 台词与旁白 + 禁区组装，【@图片N】的 N 就是 files 里的第 N 个；
    旧格式分镜照旧发 video_prompt 原文（不另起一套编号）。
    extra_refs：追加在资产之后的图（如上一段尾帧），同样计入编号。genre 仅保留兼容调用方。
    warnings：有画内台词却没参考图的角色、本段内连续 3 个小镜头同一景别。
    """
    refs = collect_refs(shot, chars, scenes, props, static_dir, scene_location) + list(extra_refs or [])
    refs = filter_refs(refs, model)
    missing_picture = not str(shot.get("video_prompt") or "").strip()
    if shot.get("lines"):
        prompt = assemble_video_prompt(shot, refs, seg_no, genre, style_suffix)
        warnings = speaker_warnings(shot, refs) + shot_size_warnings([shot])
        if missing_picture:
            warnings.append("本段缺少 AI 画面描述（video_prompt 为空），未自动生成，请补充后再生成")
    else:
        prompt = shot.get("video_prompt") or shot.get("prompt", "") or ""
        warnings = []
        if missing_picture:
            warnings.append("本段缺少画面提示词，请补充后再生成")
    warnings = warnings + form_warnings(refs)
    return {"files": [r["path"] for r in refs], "refs": refs, "prompt": prompt, "warnings": warnings}
