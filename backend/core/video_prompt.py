"""视频段 → 发给视频模型的完整提示词，由代码按实际上传的参考图顺序组装。

【整体设定】画面人物（名字）+ 时辰 + 环境 + 光影（按 mood 映射，见 core.genre_rhythm.lighting_for_mood）+ 情绪基调
【硬性参数】段号、严格时长、画幅、无水印标识
【参考素材】图1..图N 各是谁/什么（只列实际会上传的图，编号 = 上传顺序）
【台词清单】全段所有发声内容（对白/旁白/心声/画外音）按序号①②③各列一次，带说话人、起止秒、发声镜头；
            声明“以上为唯一发声依据”，每句只说一次、禁止回放回声双重人声、其他镜头与人物不发声。台词原文只在这里出现
【画面】     画面时间轴（shots.video_prompt，由 core.shot_timing.compose_video_prompt 生成）：每个小镜头写机位构图、
            承接上一镜结尾、“此时说出台词②”（不重复原文）、特效边界；多张场景图时每个小镜头标“背景参考【@图片N】”
【硬性禁区】严格时长不压缩、无水印、无随机字幕、五官服装一致、光影统一、未出场角色不提前出现、
            同一镜头同一角色只有一个实体、群演各异、同场景站位朝向不镜像
长度预算 MAX_PROMPT_CHARS：超出时先去重复的禁区套话，再缩短画面里的形容；台词清单和硬性参数不裁。

编号不交给大模型：模型只写名字，这里按上传顺序替换，避免图号对不上。
旧格式分镜（没有 lines）不经过这里，照旧发 video_prompt 原文。
"""
import re
from pathlib import Path
from typing import Dict, List, Optional

from core.genre_rhythm import lighting_for_mood
from core.shot_timing import NARRATOR, circled, fx_boundary_warnings, shot_size_warnings, speak_tag

ASPECT = "16:9 横屏"
MAX_PROMPT_CHARS = 1800          # 完整提示词的长度预算（豆包网页是否有上限未确认，做成可配置；测试可改）
TRIMMED_WARNING = "提示词已按长度预算精简"
OVER_BUDGET_WARNING = "提示词精简后仍超出长度预算（{n} 字 / 预算 {m} 字），请手动缩短画面描述"
# 时辰：从段的 scene（场景名 + 时段光线氛围）里识别；长词在前，先命中先用
_TIME_WORDS = ("凌晨", "黎明", "破晓", "拂晓", "清晨", "早晨", "早上", "一早", "上午", "正午", "中午", "午后", "下午",
               "黄昏", "傍晚", "日落", "入夜", "夜晚", "深夜", "半夜", "午夜", "子夜", "夜里", "晚上", "雨夜", "雪夜",
               "白天", "白日", "夜")
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
        extra = {k: b[k] for k in ("form", "warning", "view") if b.get(k)}
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


_VIEW_SPLIT = re.compile(r"[·\-—_/（）()\s　,，、]+")
_VIEW_SUFFIX = ("视角", "角度", "方向", "机位", "朝向", "一侧", "方位")


def _view_tokens(ref: Dict) -> set:
    """场景图的视角关键词：名字按分隔符拆开 + view 字段，去掉“视角”等后缀；长度≥2。"""
    out = set()
    for piece in _VIEW_SPLIT.split(f"{ref.get('name') or ''} {ref.get('view') or ''}"):
        for suf in _VIEW_SUFFIX:
            if piece.endswith(suf) and len(piece) > len(suf):
                piece = piece[: -len(suf)]
        if len(piece) >= 2:
            out.add(piece)
    return out


def pick_scene_ref(beat: dict, scene_refs: List[tuple]) -> tuple:
    """小镜头用哪张背景图：只看各场景图“独有”的视角词（共有的场景名不算）在小镜头构图、机位、动作里命中最多的；
    匹配不上用第一张。scene_refs = [(图号, ref)]。"""
    toks = [_view_tokens(r) for _, r in scene_refs]
    common = set.intersection(*toks) if toks else set()
    text = " ".join(str((beat or {}).get(k) or "") for k in ("composition", "camera", "shot_size", "move", "action"))
    best, best_score = scene_refs[0], 0
    for (n, r), t in zip(scene_refs, toks):
        score = sum(1 for w in t - common if w in text)
        if score > best_score:
            best, best_score = (n, r), score
    return best


def tag_backgrounds(picture: str, shot: dict, refs: List[Dict]) -> str:
    """多张场景图（同一场景的多个视角）时，【画面】每个小镜头时间段后标“背景参考【@图片N】”，按小镜头的
    构图/机位匹配；只有一张场景图时整段在开头写一次；没有场景图不写。必须在 tag_panels 之前调用。"""
    scene_refs = [(i, r) for i, r in enumerate(refs, start=1) if r["type"] == "场景"]
    if not scene_refs:
        return picture
    if len(scene_refs) == 1:
        return f"背景参考【@图片{scene_refs[0][0]}】；{picture}"
    beats = [b for b in (shot.get("beats") or []) if isinstance(b, dict)]
    it = iter(beats)

    def sub(m):
        b = next(it, None)
        if b is None:
            return m.group(0)
        return f"{m.group(0)}背景参考【@图片{pick_scene_ref(b, scene_refs)[0]}】；"

    out = _TIME_SPAN.sub(sub, picture)
    return out if out != picture else f"背景参考【@图片{scene_refs[0][0]}】；{picture}"


_SAY_VERB = r"(?:说出|说|喊|道|问|低声说|冷声说)[:：]\s*"
MIN_DEDUPE_CHARS = 4


def dedupe_dialogue(picture: str, lines: list) -> str:
    """【画面】里不重复台词原文：旧数据 / 手写画面里残留的“某某说：台词”换成“说出台词②”，裸原文换成“台词②”。"""
    from core.shot_timing import spoken_chars

    for i, ln in enumerate(lines or [], start=1):
        text = str(ln.get("text") or "").strip().rstrip("。；;，,！？!?…")
        if not text or spoken_chars(text) < MIN_DEDUPE_CHARS or text not in picture:
            continue
        mark = f"说出台词{circled(i)}"
        picture = re.sub(_SAY_VERB + re.escape(text) + r"[。；;，,！？!?…]*", mark, picture)
        picture = picture.replace(text, f"台词{circled(i)}")
    return picture


def _beat_index_of_line(beats: list, line_no: int, line: dict) -> int:
    """第 line_no 句台词在第几个小镜头发声（1 起；找不到 0）：先看 line_refs，再看起点落在哪个小镜头里。"""
    for bi, b in enumerate(beats or [], start=1):
        if isinstance(b, dict) and line_no in (b.get("line_refs") or []):
            return bi
    st = line.get("start")
    if st is not None:
        for bi, b in enumerate(beats or [], start=1):
            if isinstance(b, dict) and b.get("start") is not None and b["start"] <= st < b.get("end", 1e9):
                return bi
    return 0


SPEECH_RULES = ("以上为唯一发声依据，后文画面描述只说明表演与发声时机，不代表再次说出；每句只说一次，禁止回放、回声、双重人声；"
                "谁在哪一镜发声以清单为准，其他镜头和其他人物不发声；台词说完自然闭嘴，不加嘟囔、笑声和语气词")


def dialogue_list(shot: dict) -> str:
    """【台词清单】正文：①②③… 每句台词在整条提示词里只在这里出现一次。"""
    lines = shot.get("lines") or []
    if not lines:
        return "本段无台词，画面中人物不开口说话"
    beats = shot.get("beats") or []
    mood = str(shot.get("mood") or "")
    people = _people(shot)
    items = []
    for i, ln in enumerate(lines, start=1):
        text = str(ln.get("text") or "").strip()
        sp = ln.get("speaker") or "旁白"
        bi = _beat_index_of_line(beats, i, ln)
        where = f"·第{bi}镜" if bi else ""
        t = f"[{_fmt(ln.get('start'))}-{_fmt(ln.get('end'))}秒{where}]"
        beat = beats[bi - 1] if bi else {}
        if ln.get("kind") == "onscreen":
            items.append(f"{circled(i)}{t}{speak_tag(sp, beat, mood, people)}{text}（{sp}露脸，口型对上）")
        elif ln.get("kind") == "offscreen":
            items.append(f"{circled(i)}{t}画外传来{sp}的声音：{text}（{sp}不在画面里）")
        else:
            who = "旁白" if ln.get("kind") == "narration" else f"{sp}心声"
            items.append(f"{circled(i)}{t}{who}：{text}（画外音，画面人物不张嘴）")
    return "；".join(items) + "。" + SPEECH_RULES


# 硬性禁区分句：(正文, 可精简)。可精简 = 与【硬性参数】/其他段重复的套话，超预算时第一步去掉
FORBID_CLAUSES = (
    ("严格时长 {dur} 秒，不压缩不加长", True),
    ("无水印、无平台标识、无角标、无logo", True),
    ("不生成任何字幕或随机文字", False),
    ("人物五官、发型、服装与参考图一致，前后不变", False),
    ("光影与色调统一", True),
    ("本段未出场的角色不要提前出现", False),
    ("同一镜头中同一角色只能出现一个实体，禁止分身、克隆、镜像重复", False),
    ("同一场景内人物的站位、朝向和左右位置前后一致，不镜像翻转", False),
    ("群演和路人长相、穿搭各不相同，不复制同一张脸", True),
    ("只要环境音和动作音，不要背景音乐、贝斯或任何音乐元素", False),
)


def _forbid(dur: str, trimmed: bool) -> str:
    return "；".join(t.format(dur=dur) for t, droppable in FORBID_CLAUSES if not (trimmed and droppable))


_SHORTENABLE = ("场景与站位", "场景基调", "角色", "音效")   # 段级的描述串；小镜头、承接、台词序号、特效边界、尾态不缩


def shorten_picture(picture: str, keep: int) -> str:
    """缩短【画面】里段级描述串（场景与站位、角色、音效）的形容：只留前 keep 个短语；
    音效去掉“只要环境音和动作音”的重复尾巴。小镜头本身、承接、台词序号、特效边界、背景参考、尾态整句保留。"""
    out = []
    for part in picture.split("；"):
        part = part.replace("，只要环境音和动作音", "")
        if part.startswith(_SHORTENABLE):
            bits = [x for x in re.split(r"[，,]", part) if x.strip()]
            if len(bits) > keep:
                part = "，".join(bits[:keep])
        out.append(part)
    return "；".join(x for x in out if x)


def trim_beat_actions(picture: str, beats: list, keep: int = 2) -> str:
    """小镜头动作只留前 keep 个短语（最后一招）；找不到动作原文就不动。"""
    for b in beats:
        act = str(b.get("action") or "").strip().rstrip("，,。；;")
        bits = [x for x in re.split(r"[，,]", act) if x.strip()]
        if len(bits) > keep:
            picture = picture.replace(act, "，".join(bits[:keep]), 1)
    return picture


MAX_TRIM_LEVEL = 5


def drop_beat_fields(picture: str, beats: list, fields: tuple) -> str:
    """从【画面】里去掉各小镜头的某些字段原文（表情、构图）；画面被用户手改过、找不到原文就不动。"""
    for b in beats:
        for f in fields:
            v = str(b.get(f) or "").strip().rstrip("，,。；;")
            if v:
                picture = picture.replace("，" + v, "", 1)
    return picture


def assemble_video_prompt_ex(shot: dict, refs: List[Dict], seg_no: Optional[int] = None, genre: str = "",
                             style_suffix: str = "") -> tuple:
    """同 assemble_video_prompt，另返回 warnings（按 MAX_PROMPT_CHARS 精简过会含 TRIMMED_WARNING）。"""
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

    raw_picture = dedupe_dialogue(str(shot.get("video_prompt") or "").strip().rstrip("；;"), shot.get("lines") or [])
    setting = overall_setting(shot, genre)
    setting = _tag_names(setting, numbering) if numbering else setting
    said_txt = dialogue_list(shot)
    style_line = f"【风格】{style_suffix.strip()}\n" if (style_suffix or "").strip() else ""

    def picture_at(level: int) -> str:
        """level 0 原样；2 去表情；3 再去构图；4 缩短场景站位/音效；5 小镜头动作只留前两个短语。背景参考、四格标注在最后加。"""
        pic = raw_picture
        beats = [b for b in (shot.get("beats") or []) if isinstance(b, dict)]
        if level >= 2:
            pic = drop_beat_fields(pic, beats, ("expression",))
        if level >= 3:
            pic = drop_beat_fields(pic, beats, ("composition",))
        if level >= 4:
            pic = shorten_picture(pic, 3)
        if level >= 5:
            pic = trim_beat_actions(pic, beats)
        pic = tag_backgrounds(pic, shot, refs)
        return tag_panels(pic, shot) if has_storyboard else pic

    def build(level: int) -> str:
        pic = picture_at(level)
        pic = _tag_names(pic, numbering) if numbering else pic
        return (f"【整体设定】{setting}\n【硬性参数】{hard}\n【参考素材】{refs_txt}\n【台词清单】{said_txt}\n"
                f"【画面】{pic}\n{style_line}【硬性禁区】{_forbid(dur, level >= 1)}")

    warnings: List[str] = []
    prompt = build(0)
    limit = int(MAX_PROMPT_CHARS or 0)
    if limit and len(prompt) > limit:
        # 从后往前裁：先去重复的禁区套话，再逐级缩短画面里的形容（表情 → 构图 → 场景站位音效 → 动作）；台词清单、硬性参数不动
        for level in range(1, MAX_TRIM_LEVEL + 1):
            prompt = build(level)
            if len(prompt) <= limit:
                break
        warnings.append(TRIMMED_WARNING)
        if len(prompt) > limit:
            warnings.append(OVER_BUDGET_WARNING.format(n=len(prompt), m=limit))
    return prompt, warnings


def assemble_video_prompt(shot: dict, refs: List[Dict], seg_no: Optional[int] = None, genre: str = "",
                          style_suffix: str = "") -> str:
    """组装完整提示词：整体设定 + 硬性参数 + 参考素材 + 台词清单 + 画面 +（风格）+ 硬性禁区。
    style_suffix 是项目媒介与题材的视频风格词（style_library.build_video_style_suffix），为空不写【风格】行。
    refs 必须是实际上传的图（顺序 = 上传顺序）；genre 是项目题材，用于光影映射的题材覆盖。
    参考里有四格分镜图时，【画面】各时间段标注对应的格（S1–S4）；多张场景图时每个小镜头标背景参考；
    超过 MAX_PROMPT_CHARS 时按优先级精简（带 warnings 的版本见 assemble_video_prompt_ex）。"""
    return assemble_video_prompt_ex(shot, refs, seg_no, genre, style_suffix)[0]


def build_upload_plan(shot: dict, chars: list, scenes: list, props: list, static_dir: Path,
                      model: dict, scene_location: str = "", seg_no: Optional[int] = None,
                      extra_refs: Optional[List[Dict]] = None, genre: str = "", style_suffix: str = "") -> Dict:
    """一次视频生成的上传计划：参考图文件（顺序 = 上传顺序）与发给模型的提示词，出自同一个 refs 列表。

    返回 {"files": [绝对路径], "refs": [...], "prompt": str, "warnings": [...]}。
    视频段（有 lines）按整体设定 + 硬性参数 + 参考素材 + 台词清单 + 画面 + 禁区组装，【@图片N】的 N 就是 files 里的第 N 个；
    旧格式分镜照旧发 video_prompt 原文（不另起一套编号）。
    extra_refs：追加在资产之后的图（如上一段尾帧），同样计入编号。genre：项目题材（光影映射可按题材覆盖）。
    warnings：有画内台词却没参考图的角色、本段内连续 3 个小镜头同一景别、有特效没写边界、按长度预算精简过。
    """
    refs = collect_refs(shot, chars, scenes, props, static_dir, scene_location) + list(extra_refs or [])
    refs = filter_refs(refs, model)
    if shot.get("lines"):
        prompt, trim_warnings = assemble_video_prompt_ex(shot, refs, seg_no, genre, style_suffix)
        warnings = speaker_warnings(shot, refs) + shot_size_warnings([shot]) + fx_boundary_warnings([shot]) + trim_warnings
    else:
        prompt = shot.get("video_prompt") or shot.get("prompt", "") or ""
        warnings = []
    warnings = warnings + form_warnings(refs)
    return {"files": [r["path"] for r in refs], "refs": refs, "prompt": prompt, "warnings": warnings}
