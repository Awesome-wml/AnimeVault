"""视频段 → 发给视频模型的完整提示词，由代码按实际上传的参考图顺序组装。

【整体设定】画面人物（名字）+ 时辰 + 环境 + 光影（按 mood 映射，见 core.genre_rhythm.lighting_for_mood）+ 情绪基调
【硬性参数】段号、严格时长、画幅、无水印标识
【参考素材】图1..图N 各是谁/什么（只列实际会上传的图，编号 = 上传顺序）
【画面】     模型写的画面时间轴（shots.video_prompt），角色/道具名替换成 名字【@图片N】
【台词与旁白】逐句起止秒；画内台词写“人物+表情说：台词”（表情来自小镜头，台词原文不动）；旁白/心声标“画外音，画面人物不张嘴”
【硬性禁区】严格时长不压缩、无水印、无随机字幕、五官服装一致、光影统一、未出场角色不提前出现、
            同一镜头同一角色只有一个实体、群演各异

编号不交给大模型：模型只写名字，这里按上传顺序替换，避免图号对不上。
旧格式分镜（没有 lines）不经过这里，照旧发 video_prompt 原文。
"""
import re
from pathlib import Path
from typing import Dict, List, Optional

from core.genre_rhythm import lighting_for_mood
from core.shot_timing import NARRATOR, beat_of_line, shot_size_warnings, speak_tag

ASPECT = "16:9 横屏"
# 时辰：从段的 scene（场景名 + 时段光线氛围）里识别；长词在前，先命中先用
_TIME_WORDS = ("凌晨", "黎明", "破晓", "拂晓", "清晨", "早晨", "早上", "一早", "上午", "正午", "中午", "午后", "下午",
               "黄昏", "傍晚", "日落", "入夜", "夜晚", "深夜", "半夜", "午夜", "子夜", "夜里", "晚上", "雨夜", "雪夜",
               "白天", "白日", "夜")
REF_LABEL = {"分镜参考": "本段首帧画面参考", "角色": "角色", "场景": "场景", "道具": "道具", "关键帧": "上一段尾帧"}
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
    """本段要上传的参考图（按上传顺序）：段首画面 → 绑定的资产。只收本地存在的图。

    “用哪些资产、什么顺序”统一由 core.asset_binding.collect_bindings 决定（角色 → 场景 → 道具；
    视频段按结构化字段，旧数据按名字匹配；场次地点参与场景归属）。
    返回 [{type, name, path, label, asset_id}]，type 为中文（分镜参考/角色/场景/道具）。
    """
    from core.asset_binding import collect_bindings

    refs: List[Dict] = []
    seen = set()

    def add(kind, name, rel, label="", asset_id=None):
        if not rel:
            return
        f = Path(static_dir) / rel
        if f.exists() and str(f) not in seen:
            seen.add(str(f))
            refs.append({"type": kind, "name": name, "path": str(f), "label": label, "asset_id": asset_id})

    add("分镜参考", "段首画面", shot.get("img_path"))
    for b in collect_bindings(shot, chars, scenes, props, scene_location=scene_location):
        add(TYPE_CN[b["asset_type"]], b["name"], b.get("img"), b.get("label") or "", b.get("asset_id"))
    return refs


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


def time_of_day(scene: str) -> str:
    """从场景描述里识别时辰（“云顶包厢，深夜，暖光转冷”→“深夜”）；识别不出返回空。"""
    s = str(scene or "")
    for w in _TIME_WORDS:
        if w in s:
            return w
    return ""


def _people(shot: dict) -> List[str]:
    """画面人物：段的 characters，再补有画内台词的说话人；去重保序。"""
    names = [str(n) for n in (shot.get("characters") or []) if n]
    for ln in shot.get("lines") or []:
        sp = ln.get("speaker")
        if ln.get("kind") == "onscreen" and sp and sp != NARRATOR and sp not in names:
            names.append(str(sp))
    return list(dict.fromkeys(names))


def overall_setting(shot: dict, genre: str = "") -> str:
    """【整体设定】一行：画面人物（名字）+ 时辰 + 环境 + 光影（按 mood 映射，题材可覆盖）+ 情绪基调。"""
    people = _people(shot)
    scene = str(shot.get("scene") or "").strip().rstrip("；;。")
    mood = str(shot.get("mood") or "").strip().rstrip("；;。")
    when = time_of_day(scene)
    bits = ["画面人物：" + ("、".join(people) if people else "无人物，纯环境")]
    if when:
        bits.append(f"时辰：{when}")
    if scene:
        bits.append(f"环境：{scene}")
    bits.append(f"光影：{lighting_for_mood(mood, genre)}")
    bits.append(f"情绪基调：{mood or '按台词与动作自然呈现'}")
    return "；".join(bits)


def assemble_video_prompt(shot: dict, refs: List[Dict], seg_no: Optional[int] = None, genre: str = "") -> str:
    """组装完整提示词：整体设定 + 硬性参数 + 参考素材 + 画面 + 台词与旁白 + 硬性禁区。
    refs 必须是实际上传的图（顺序 = 上传顺序）；genre 是项目题材，用于光影映射的题材覆盖。"""
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
    setting = overall_setting(shot, genre)
    setting = _tag_names(setting, numbering) if numbering else setting

    said = []
    beats = shot.get("beats") or []
    mood = str(shot.get("mood") or "")
    people = _people(shot)
    for i, ln in enumerate(shot.get("lines") or [], start=1):
        t = f"[{_fmt(ln.get('start'))}-{_fmt(ln.get('end'))}秒]"
        text = str(ln.get("text") or "").strip()
        sp = ln.get("speaker") or "旁白"
        if ln.get("kind") == "onscreen":
            said.append(f"{t}{speak_tag(sp, beat_of_line(beats, i), mood, people)}{text}"
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
    return (f"【整体设定】{setting}\n【硬性参数】{hard}\n【参考素材】{refs_txt}\n【画面】{picture}\n"
            f"【台词与旁白】{said_txt}\n【硬性禁区】{forbid}")


def build_upload_plan(shot: dict, chars: list, scenes: list, props: list, static_dir: Path,
                      model: dict, scene_location: str = "", seg_no: Optional[int] = None,
                      extra_refs: Optional[List[Dict]] = None, genre: str = "") -> Dict:
    """一次视频生成的上传计划：参考图文件（顺序 = 上传顺序）与发给模型的提示词，出自同一个 refs 列表。

    返回 {"files": [绝对路径], "refs": [...], "prompt": str, "warnings": [...]}。
    视频段（有 lines）按整体设定 + 五段结构组装，【@图片N】的 N 就是 files 里的第 N 个；
    旧格式分镜照旧发 video_prompt 原文（不另起一套编号）。
    extra_refs：追加在资产之后的图（如上一段尾帧），同样计入编号。genre：项目题材（光影映射可按题材覆盖）。
    warnings：有画内台词却没参考图的角色、本段内连续 3 个小镜头同一景别。
    """
    refs = collect_refs(shot, chars, scenes, props, static_dir, scene_location) + list(extra_refs or [])
    refs = filter_refs(refs, model)
    if shot.get("lines"):
        prompt = assemble_video_prompt(shot, refs, seg_no, genre)
        warnings = speaker_warnings(shot, refs) + shot_size_warnings([shot])
    else:
        prompt = shot.get("video_prompt") or shot.get("prompt", "") or ""
        warnings = []
    return {"files": [r["path"] for r in refs], "refs": refs, "prompt": prompt, "warnings": warnings}
