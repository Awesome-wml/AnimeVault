"""视频段 → 发给视频模型的完整提示词，由代码按实际上传的参考图顺序组装。

【整体设定】画面人物（名字）+ 时辰 + 环境 + 光影（按 mood 映射，见 core.genre_rhythm.lighting_for_mood）+ 情绪基调
【硬性参数】段号、严格时长、画幅、无水印标识
【首帧承接】有上一段尾帧参考时：第 0 帧以它为准，前 N 秒保持姿势站位（N 来自 core.pacing）
【参考素材】每张实际上传的图一条 “[名字](refN)：这张图是什么、约束什么”（尾帧 / 四格分镜 / 首帧 / 角色主讲或出场+形态 /
            场景背景 / 道具外观），编号 = 上传顺序；发送前 doubao_automation._compose_prompt 把 (refN) 换成附件芯片
【角色参考】【场景参考】角色五官体型服装、场景全程锁定（e087665）
【台词清单】全段所有发声内容（对白/旁白/心声/画外音）按序号①②③各列一次，带说话人、起止秒、发声镜头；
            声明“以上为唯一发声依据”，每句只说一次、禁止回放回声双重人声、其他镜头与人物不发声。台词原文只在这里出现
【画面】     画面时间轴（shots.video_prompt，由 core.shot_timing.compose_video_prompt 生成）：每个小镜头写机位构图、
            承接上一镜结尾、“此时说出台词②”（不重复原文）、特效边界；多张场景图时每个小镜头标“背景参考[场景名](refN)”
【人物细节】有人物出镜的镜头必带：眨眼/呼吸/视线/微表情基础层 + 逐人表情（beat.expression）+ 口型对齐；无人镜头不写
【硬性禁区】严格时长不压缩、无水印、无字幕与任何文字（最后一条）、五官服装一致、光影统一、未出场角色不提前出现、
            同一镜头同一角色只有一个实体、群演各异、同场景站位朝向不镜像
长度预算 MAX_PROMPT_CHARS：超出时先去重复的禁区套话，再缩短画面里的形容；台词清单、硬性参数、人物细节不裁（最后一级才压成核心句）。

编号不交给大模型：模型只写名字，这里按上传顺序替换，避免图号对不上。
旧格式分镜（没有 lines）不经过这里，照旧发 video_prompt 原文。
"""
import re
from pathlib import Path
from typing import Dict, List, Optional

from core.bystander import DOWN_ACTION, _RELAX, _is_seated, is_action_shot, is_down, shot_people
from core.genre_rhythm import lighting_for_mood
from core.pacing import FIRST_FRAME_HOLD_SECONDS, fmt_number
from core.shot_timing import (beat_rhythm_warnings, circled, fx_boundary_warnings, shot_size_warnings, speak_tag,
                              speech_overflow_warnings)

ASPECT = "16:9 横屏"
# 旁白（画外叙述音）固定音色：全片同一人，不随段落/镜头切换男女声；角色对白音色不在此约束
NARRATOR_VOICE = "沉稳青年男声"
NARRATOR_VOICE_RULE = (f"旁白（画外叙述音）统一使用{NARRATOR_VOICE}，全片保持同一个人发声，前后段音色一致，"
                       f"不得在男声/女声之间切换，不得每条旁白更换音色")
MAX_PROMPT_CHARS = 153600        # 完整提示词的长度预算：按 256k 上限的 60% 放宽（256000×0.6），实际几乎不会触发精简；测试可改
TRIMMED_WARNING = "提示词已按长度预算精简"
OVER_BUDGET_WARNING = "提示词精简后仍超出长度预算（{n} 字 / 预算 {m} 字），请手动缩短画面描述"
# 时辰：从段的 scene（场景名 + 时段光线氛围）里识别；长词在前，先命中先用
_TIME_WORDS = ("凌晨", "黎明", "破晓", "拂晓", "清晨", "早晨", "早上", "一早", "上午", "正午", "中午", "午后", "下午",
               "黄昏", "傍晚", "日落", "入夜", "夜晚", "深夜", "半夜", "午夜", "子夜", "夜里", "晚上", "雨夜", "雪夜",
               "白天", "白日", "夜")
# 分镜参考图有两种：四格图（T-215 起，优先）和旧的单张首帧（旧段没有四格图时回退）；ref 的 name 区分
STORYBOARD_NAME, FRAME_NAME = "四格分镜", "段首画面"
# 【参考素材】里各类图的语义（R2）：告诉视频模型这张图是什么、只约束什么，S1–S4 标注才有定义
STORYBOARD_LABEL = "本段四格分镜，左上→右上→左下→右下 依次对应下文画面里标 S1–S4 的四个时间段，只约束各时段的构图、站位与光影"
FRAME_LABEL = "本段首帧画面参考（构图与光影以此为准）"
TAIL_LABEL = "本段第 0 帧以此图为准（姿势、站位、朝向、构图、光影、服饰全部承接）"
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


_LINK_RE = re.compile(r"\[[^\]]*\]\([^)]*\)")


def _tag_names(text: str, numbering: Dict[str, int]) -> str:
    """名字 → [名字](refN)；长名字先替换，已有链接不二次包裹；台词（“说：”之后到分号）里的名字不动。"""
    names = sorted(numbering, key=len, reverse=True)
    pattern = re.compile("|".join(re.escape(n) for n in names))

    def tag(chunk: str) -> str:
        if not names:
            return chunk
        # 已有链接片段（如背景参考）先占位保护，避免里面的名字被二次包裹成嵌套链接
        links = []
        def stash(m):
            links.append(m.group(0))
            return f"\x00{len(links) - 1}\x00"
        chunk = _LINK_RE.sub(stash, chunk)
        chunk = pattern.sub(lambda m: f"[{m.group(0)}](ref{numbering[m.group(0)]})", chunk)
        for i, link in enumerate(links):
            chunk = chunk.replace(f"\x00{i}\x00", link)
        return chunk

    out, pos = [], 0
    for m in _SPOKEN_SPAN.finditer(text):
        out.append(tag(text[pos:m.start()]))
        out.append(m.group(0))
        pos = m.end()
    out.append(tag(text[pos:]))
    return "".join(out)


def ref_semantics(shot: dict, refs: List[Dict]) -> List[str]:
    """【参考素材】每张图一条 “[名字](refN)：这张图是什么、约束什么”，编号 = refs 顺序 = 上传顺序（R2）。

    e087665 删掉这一段后，四格分镜、段首画面、道具图上传了却在提示词里零引用（S1–S4 标注悬空、(refN) 锚点缺失
    导致 _compose_prompt 不会把它们换成附件芯片），角色图也丢了“主讲/出场 + 形态名”。
    角色：本段有画内台词的写“本段主讲”，否则“出场”；多形态角色带形态名，旧数据的“单形态”不写。
    """
    from core.character_forms import SINGLE_FORM_NAME

    speaking = {ln.get("speaker") for ln in (shot.get("lines") or []) if ln.get("kind") == "onscreen"}
    has_tail = any(r["type"] == "关键帧" for r in refs)
    out = []
    for i, r in enumerate(refs, start=1):
        kind, name = r["type"], r.get("name") or r["type"]
        if kind == "关键帧":
            desc = TAIL_LABEL
        elif kind == "分镜参考" and name == STORYBOARD_NAME:
            desc = STORYBOARD_LABEL + ("；开场第 0 帧以上一段尾帧为准" if has_tail else "")
        elif kind == "分镜参考":
            desc = FRAME_LABEL
        elif kind == "角色":
            form = f"，{r['form']}" if r.get("form") and r["form"] != SINGLE_FORM_NAME else ""
            desc = f"角色，{'本段主讲' if name in speaking else '出场'}{form}，五官服装以此为准"
        elif kind == "场景":
            view = f"，{r['view']}" if r.get("view") and r["view"] not in name else ""
            desc = f"场景背景{view}"
        elif kind == "道具":
            desc = "道具外观"
        else:
            desc = kind
        out.append(f"[{name}](ref{i})：{desc}")
    return out


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
    return shot_people(shot)


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
    bits.append(f"光影：{lighting_for_mood(mood, genre, scene)}")
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
    """多张场景图（同一场景的多个视角）时，【画面】每个小镜头时间段后标“背景参考[场景名](refN)”，按小镜头的
    构图/机位匹配；只有一张场景图时整段在开头写一次；没有场景图不写。必须在 tag_panels 之前调用。"""
    scene_refs = [(i, r) for i, r in enumerate(refs, start=1) if r["type"] == "场景"]
    if not scene_refs:
        return picture
    if len(scene_refs) == 1:
        n, r = scene_refs[0]
        return f"背景参考[{r['name']}](ref{n})；{picture}"
    beats = [b for b in (shot.get("beats") or []) if isinstance(b, dict)]
    it = iter(beats)

    def sub(m):
        b = next(it, None)
        if b is None:
            return m.group(0)
        n, r = pick_scene_ref(b, scene_refs)
        return f"{m.group(0)}背景参考[{r['name']}](ref{n})；"

    out = _TIME_SPAN.sub(sub, picture)
    n, r = scene_refs[0]
    return out if out != picture else f"背景参考[{r['name']}](ref{n})；{picture}"


_SAY_VERB = r"(?:说出|说|喊|道|问|低声说|冷声说)[:：]\s*"
MIN_DEDUPE_CHARS = 4


def dedupe_dialogue(picture: str, lines: list, beats: list = None) -> str:
    """【画面】里不重复台词原文：旧数据 / 手写画面里残留的“某某说：台词”换成“说出台词②”，裸原文换成“台词②”。"""
    from core.shot_timing import spoken_chars

    for i, ln in enumerate(lines or [], start=1):
        text = str(ln.get("text") or "").strip().rstrip("。；;，,！？!?…")
        if not text or spoken_chars(text) < MIN_DEDUPE_CHARS or text not in picture:
            continue
        mark = f"说出台词{circled(i)}"
        picture = re.sub(_SAY_VERB + re.escape(text) + r"[。；;，,！？!?…]*", mark, picture)
        if ln.get("kind") == "narration" and any(
                isinstance(b, dict) and text in str(b.get("action") or "") for b in beats or []):
            # 旁白和小镜头动作一字不差（“沈砚瞳孔骤缩”）：整句换成“台词③”会把画面动作抹掉，只处理“说：…”的写法
            continue
        picture = picture.replace(text, f"台词{circled(i)}")
    return picture


def inject_others(picture: str, shot: dict) -> str:
    """T-273：每个小镜头的焦点动作之后拼“其余在场者：…”。已经写了（新数据 compose 时带上）的不重复；
    老数据（画面是旧版生成、beats 没有 others）由 core.bystander 按在场人物兜底，逐人不同动作。"""
    from core.bystander import LABEL, beat_phrases

    beats = [b for b in (shot.get("beats") or []) if isinstance(b, dict)]
    phrases = beat_phrases(dict(shot, beats=beats)) if beats else []
    marks = list(_TIME_SPAN.finditer(picture))
    if not marks or not any(phrases):
        return picture
    out, pos = [], 0
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(picture)
        chunk = picture[m.end():end]
        phrase = phrases[i] if i < len(phrases) else ""
        if phrase and LABEL not in chunk:
            b = beats[i]
            act = "，".join(x for x in (b.get("action"), b.get("expression")) if x)
            at = chunk.find(act) + len(act) if act and act in chunk else -1
            if at < 0:   # 画面被手改过、找不到动作原文：插在台词/音效/尾态之前，都没有就接在本镜末尾
                cuts = [chunk.find(k) for k in ("；此时", "；特效边界", "；音效：", "；尾态：") if chunk.find(k) >= 0]
                at = min(cuts) if cuts else len(chunk.rstrip("；;"))
            chunk = chunk[:at] + "；" + phrase + chunk[at:]
        out.append(picture[pos:m.end()] + chunk)
        pos = end
    return "".join(out) + picture[pos:]


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
    has_narr = False
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
            if ln.get("kind") == "narration":
                has_narr = True
                who = f"旁白（{NARRATOR_VOICE}）"
            else:
                who = f"{sp}心声"
            items.append(f"{circled(i)}{t}{who}：{text}（画外音，画面人物不张嘴）")
    tail = "。" + SPEECH_RULES
    if has_narr:
        tail += "；" + NARRATOR_VOICE_RULE
    return "；".join(items) + tail


# 硬性禁区分句：(正文, 可精简)。可精简 = 与【硬性参数】/其他段重复的套话，超预算时第一步去掉
FORBID_CLAUSES = (
    ("严格时长 {dur} 秒，不压缩不加长", True),
    ("无水印、无平台标识、无角标、无logo", True),
    ("人物五官、发型、服装与参考图一致，前后不变", False),
    ("光影与色调统一", True),
    ("本段未出场的角色不要提前出现", False),
    ("同一镜头中同一角色只能出现一个实体，禁止分身、克隆、镜像重复", False),
    ("同一场景内人物的站位、朝向和左右位置前后一致，不镜像翻转", False),
    # R4：拆分镜允许清单外的路人“只做反应、用身份描述（围观族人）”，禁区不能一概禁掉其他人物；
    # 群像只能是【画面】点到的那一撮，背景反应、不给正脸、不复制同一张脸
    ("除【整体设定】列出的角色和【画面】明确点到的群像（如围观族人）外，不得出现其他人物、路人、背景人影或虚影；"
     "群像只做背景反应，不给正脸特写、不与主角同框近景，长相穿搭各不相同、不复制同一张脸", False),
    ("禁止白模、石膏人、无五官或未渲染完成的人形、半透明幽灵人", False),
    ("只要环境音和动作音，不要背景音乐、贝斯或任何音乐元素", False),
    # 必须是最后一条：自动回复豆包的操作用语（确认、开始生成）曾被渲染成画面底部字幕
    ("画面不出现任何字幕或文字（包括「确认」「开始生成」等操作用语）", False),
)


def _forbid(dur: str, trimmed: bool) -> str:
    return "；".join(t.format(dur=dur) for t, droppable in FORBID_CLAUSES if not (trimmed and droppable))


# 【人物细节】基础层：每个有人物出镜的镜头都带，写成视频模型可执行的正向描述；超预算时最后才压缩（核心句不删）
DETAIL_CORE = ("自然眨眼（约每3-5秒一次，不连续眨）、胸口随呼吸轻微起伏、视线有落点并自然游移、"
               "面部肌肉有细微表情变化；双眼自然睁开，禁止面无表情瞪眼、眼睛半闭定格、僵直不动")
DETAIL_SPEAK = "说话时口型与台词对齐"
DETAIL_SILENT = "不说话时嘴唇自然闭合不张嘴，仍有轻微点头、吞咽或手指小动作"
DETAIL_NEUTRAL = "神态自然放松"      # beat 没写表情时的中性基线


_CROWD_SUBJECT = re.compile(r"^(?:[一两二三几数十]+[名个位]|众|其余|剩下的|外圈|远处)?[\u4e00-\u9fa5]{0,3}"
                            r"(?:黑衣人|蒙面人|人群|众人|手下|弟子|侍卫|士兵|守卫|族人|路人|黑影)")


def _beat_subject(b: dict, people: list, lines: list) -> Optional[str]:
    """小镜头表情归谁：本镜有画内台词时归说话人；动作以“他/她”开头（没点名）时返回 None（不硬分）；
    否则归动作里最先出现的人名；都没有返回空串（全段共用的候选）。

    原来只看动作里最先出现的名字，“他抬刀指向沈砚方向”会把铁面具的“下颌微抬，语气倨傲”记到沈砚头上。"""
    for r in b.get("line_refs") or []:
        if 1 <= r <= len(lines) and lines[r - 1].get("kind") == "onscreen" and lines[r - 1].get("speaker") in people:
            return lines[r - 1]["speaker"]
    act = str(b.get("action") or "").strip()
    hits = [(act.find(n), n) for n in people if n and n in act]
    if hits and not act.startswith(("他", "她")):
        return min(hits)[1]
    # 动作的主语是清单外的人（“两名黑衣人闷声倒下”“黑衣人举刀冲来”）：表情是他们的，不记到主角头上
    if _CROWD_SUBJECT.match(act):
        return None
    # 动作里没点名（“他抬手按住左肩”“睫毛轻颤”）：机位写了拍谁（“正对沈砚侧脸”）就归谁；
    # 构图只认开头点名的（“沈砚头肩…”）——“手腕特写，铁面具手指僵直”里出指的是另一个人
    cam = str(b.get("camera") or "")
    named = [n for n in people if n and n in cam]
    if len(named) == 1:
        return named[0]
    comp = str(b.get("composition") or "").strip()
    lead = [n for n in people if n and comp.startswith(n)]
    if lead:
        return max(lead, key=len)
    return None if act.startswith(("他", "她")) else ""


def _person_expression(name: str, beats: list, people: list = (), lines: list = ()) -> str:
    """该人物在各小镜头里的表情（beat.expression 为主）：此人是该小镜头主语（见 _beat_subject）时归他；
    动作里没点名、也没有说话人的小镜头，表情全段一致时才共用；去重保序，没有返回空。"""
    own, shared = [], []
    for b in beats:
        expr = str(b.get("expression") or "").strip().rstrip("，,。；;")
        if not expr or expr in ("无", "无表情"):
            continue
        subject = _beat_subject(b, list(people or [name]), list(lines or []))
        if subject:
            if subject == name:
                own.append(expr)
        elif subject == "":
            shared.append(expr)
    # 没点名的表情只在段里就一个人时归他：两个人时分不清是谁的（“睫毛微颤”曾被记到持刀的黑衣人头上）
    exprs = own or (shared if len(set(shared)) == 1 and len(list(people or [name])) <= 1 else [])
    return "→".join(dict.fromkeys(exprs))


# 不说话的人各自的习惯性小动作（逐人轮换，不是同一套话）
SILENT_HABITS = ("随对方语气轻微点头、偶尔吞咽", "拇指摩挲指节、重心左右微调", "视线游移后落回对方，手指轻敲膝头",
                 "偶尔清嗓、整理衣角", "下巴微抬又收回，手臂小幅换姿势")


ACTION_HABITS = ("呼吸略急、目光紧跟对手", "肩背绷紧、重心随动作前后微调", "下颌绷紧、手指收紧又松开",
                 "胸口起伏明显、视线不离场中", "脚下小幅挪步调整站位")
DETAIL_NEUTRAL_ACTION = "神情专注紧绷"
TENSE_HABITS = ("目光沉着地盯住对方、呼吸放缓", "下颌微收、手指缓缓收拢", "重心微调、视线不离对方",
                "肩背挺直、眼睫偶尔轻动", "指节收紧又松开、喉结微动")
SOLO_HABITS = ("呼吸随情绪起伏、视线落在手头的动作上",)
# 色调词与本段环境冲突时的处理：题材默认色调是按题材固定的（仙侠＝云雾仙光），雨夜暗巷里照抄会把画面带亮带仙
_DARK_SCENE = ("夜", "雨", "暗", "巷", "废墟", "牢", "地下", "阴")
_BRIGHT_TONE = ("仙光", "云雾", "瑰丽", "明亮", "暖色", "阳光", "高饱和", "清新", "柔光")
SCENE_TONE_HINT = "色调与明暗以【整体设定】的环境和光影为准"


def fit_style_to_scene(style_suffix: str, scene: str) -> str:
    """风格后缀里与本段环境冲突的色调短语去掉，换成“以本段环境为准”。不冲突原样返回。"""
    text = (style_suffix or "").strip()
    if not text or not any(w in str(scene or "") for w in _DARK_SCENE):
        return text
    parts = [p for p in re.split(r"[，,]", text) if p.strip()]
    kept = [p for p in parts if not any(w in p for w in _BRIGHT_TONE)]
    if len(kept) == len(parts):
        return text
    return "，".join(kept + [SCENE_TONE_HINT])


def character_detail(shot: dict, compact: bool = False) -> str:
    """【人物细节】正文；无人物返回空串。基础层（眨眼/呼吸/视线）只写一次，之后逐人具名：
    说话者写口型对齐，非说话者写闭嘴 + 各自不同的习惯小动作；表情以 beat.expression 为主，没有则用中性基线。
    每个小镜头里谁在做什么见【画面】的“其余在场者”。compact=True 只留核心句（预算吃紧时用）。"""
    people = _people(shot)
    if not people:
        return ""
    if compact:
        return f"所有出镜人物：{DETAIL_CORE}"
    beats = [b for b in (shot.get("beats") or []) if isinstance(b, dict)]
    speakers = {ln.get("speaker") for ln in shot.get("lines") or [] if ln.get("kind") == "onscreen"}
    per, silent_i = [], 0
    action = is_action_shot(shot)
    # 倾听小动作（“随对方语气点头”）只在有人开口的文戏里用；打斗、追逐和纯旁白段换成动作戏的状态
    # “随对方语气点头”是坐着聊天、气氛轻松时的动作；站着对峙（困局、讥讽、怨毒）时对敌人点头是穿帮
    easy = _is_seated(shot, {}) or any(w in str(shot.get("mood") or "") for w in _RELAX)
    habits = ACTION_HABITS if (action or not speakers) else (SILENT_HABITS if easy else TENSE_HABITS)
    if len(people) == 1 and not action:
        habits = SOLO_HABITS      # 独自一人的文戏：没有“对手”可盯
    for n in people:
        expr = _person_expression(n, beats, people, shot.get("lines") or [])
        look = f"表情随情绪走：{expr}" if expr else (DETAIL_NEUTRAL if (easy and not action) else DETAIL_NEUTRAL_ACTION)
        if n in speakers:
            act = DETAIL_SPEAK
        elif is_down(n, shot):
            per.append(f"{n}：不说话，{DOWN_ACTION}")     # 倒地的人不写“神态放松/专注”
            continue
        else:
            act = f"不说话时嘴唇自然闭合不张嘴，{habits[silent_i % len(habits)]}"
            silent_i += 1
        per.append(f"{n}：{look}，{act}")
    return f"所有出镜人物：{DETAIL_CORE}；" + "；".join(per)


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
    has_storyboard = False
    tail_idx: Optional[int] = None
    tail_name: Optional[str] = None
    for i, r in enumerate(refs, start=1):
        if r["type"] == "分镜参考" and r.get("name") == STORYBOARD_NAME:
            has_storyboard = True
        elif r["type"] == "关键帧":
            tail_idx = i
            tail_name = r.get("name") or "首帧"
        if r["type"] in ("角色", "道具", "场景"):
            numbering.setdefault(r["name"], i)

    # 角色/场景身份锁定块（有无首帧参考都生成）：五官体型服装与场景全程锁定，避免与清单重复
    role_refs = [r for r in refs if r["type"] == "角色"]
    scene_refs = [r for r in refs if r["type"] == "场景"]
    role_bits = "、".join(
        f"[{r['name']}](ref{numbering[r['name']]})：{r['name']}五官、体型、服装全程锁定不变" for r in role_refs)
    scene_bits = "、".join(
        f"[{r['name']}](ref{numbering[r['name']]})：{r['name']}场景参考" for r in scene_refs)
    identity_parts = []
    if role_bits:
        identity_parts.append(f"【角色参考】{role_bits}")
    if scene_bits:
        identity_parts.append(f"【场景参考】{scene_bits}")
    identity_block = "\n".join(identity_parts) + ("\n" if identity_parts else "")
    # 【参考素材】：每张上传的图说明自己是什么（R2）；没有参考图时不写这一段
    ref_lines = ref_semantics(shot, refs)
    refs_block = f"【参考素材】{'；'.join(ref_lines)}\n" if ref_lines else ""

    # 首帧承接强指令块（仅存在尾帧参考时生成）：固定模板 + 动态图号，不随精简级别裁剪。
    # 首帧图同样走 [名字](refN) 占位，发送前替换成 attachment 芯片，与角色/场景引用同一链路。
    # R10：保持秒数来自 core.pacing（原写死 2 秒且“不许变表情”，0.5 秒就开口的首句台词会被压住）；允许开口与微表情
    tail_block = ""
    if tail_idx:
        hold = fmt_number(FIRST_FRAME_HOLD_SECONDS)
        tail_parts = [
            f"【首帧承接·最高优先级】[{tail_name}](ref{tail_idx})为本段视频起始首帧，第0帧必须与该图完全一致："
            f"人物姿势、站位、朝向、构图、机位、光影、服饰、面部状态、背景全部承接该图；"
            f"本段是上一段视频的直接延续，不重新开局、不重置造型、不瞬移人物位置。"
            f"首帧对齐后，前 {hold} 秒内保持人物姿势、站位与朝向，可以开口说话和做微表情，"
            f"不突然起势、不硬切姿态，延续上一段结尾状态；"
            f"满 {hold} 秒之后，再从上一姿态自然连贯地平滑过渡到本段下一个动作与画面，演变顺滑、不跳帧、不瞬移。"
        ]
        tail_block = "\n".join(tail_parts) + "\n"

    raw_picture = dedupe_dialogue(str(shot.get("video_prompt") or "").strip().rstrip("；;"), shot.get("lines") or [], shot.get("beats"))
    raw_picture = inject_others(raw_picture, shot)   # T-273：老数据缺“其余在场者”时兜底，预算裁剪各级都不去掉它
    setting = overall_setting(shot, genre)
    setting = _tag_names(setting, numbering) if numbering else setting
    said_txt = dialogue_list(shot)
    style_suffix = fit_style_to_scene(style_suffix, shot.get("scene"))
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
        detail = character_detail(shot, compact=level >= MAX_TRIM_LEVEL)
        # 与【画面】同一行（段落顺序是既有契约），以“；【人物细节】”接在画面之后
        detail_txt = f"；【人物细节】{_tag_names(detail, numbering) if numbering else detail}" if detail else ""
        return (f"【整体设定】{setting}\n【硬性参数】{hard}\n{tail_block}{refs_block}{identity_block}【台词清单】{said_txt}\n"
                f"【画面】{pic}{detail_txt}\n{style_line}【硬性禁区】{_forbid(dur, level >= 1)}")

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
    """组装完整提示词：整体设定 + 硬性参数 +（首帧承接）+（参考素材）+（角色/场景参考）+ 台词清单 + 画面 +（风格）+ 硬性禁区。
    style_suffix 是项目媒介与题材的视频风格词（style_library.build_video_style_suffix），assemble_video_prompt 为空不写【风格】行；build_upload_plan 为空时取缺省媒介（真人实拍）补上。
    refs 必须是实际上传的图（顺序 = 上传顺序）；genre 是项目题材，用于光影映射的题材覆盖。
    参考里有四格分镜图时，【画面】各时间段标注对应的格（S1–S4）；多张场景图时每个小镜头标背景参考；
    超过 MAX_PROMPT_CHARS 时按优先级精简（带 warnings 的版本见 assemble_video_prompt_ex）。"""
    return assemble_video_prompt_ex(shot, refs, seg_no, genre, style_suffix)[0]


def build_upload_plan(shot: dict, chars: list, scenes: list, props: list, static_dir: Path,
                      model: dict, scene_location: str = "", seg_no: Optional[int] = None,
                      extra_refs: Optional[List[Dict]] = None, genre: str = "", style_suffix: str = "") -> Dict:
    """一次视频生成的上传计划：参考图文件（顺序 = 上传顺序）与发给模型的提示词，出自同一个 refs 列表。

    返回 {"files": [绝对路径], "refs": [...], "prompt": str, "warnings": [...]}。
    视频段（有 lines）按整体设定 + 硬性参数 + 参考素材 + 台词清单 + 画面 + 禁区组装，链接里 refN 的 N 就是 files 里的第 N 个；
    旧格式分镜照旧发 video_prompt 原文（不另起一套编号）。
    extra_refs：首帧参考图（如上一段尾帧），排在资产之前优先上传，同样计入编号。genre：项目题材（光影映射可按题材覆盖）。
    warnings：有画内台词却没参考图的角色、本段内连续 3 个小镜头同一景别、有特效没写边界、按长度预算精简过。
    """
    # 尾帧首帧参考排最前：多图参考下首图权重最高，优先被当作开场画面基准；refN 编号由组装层实时生成，与上传顺序对齐
    refs = list(extra_refs or []) + collect_refs(shot, chars, scenes, props, static_dir, scene_location)
    refs = filter_refs(refs, model)
    if not (style_suffix or "").strip():  # 【风格】行任何情况下都要有：调用方没传时取缺省媒介
        from core.style_library import build_video_style_line
        style_suffix = build_video_style_line()
    if shot.get("lines"):
        prompt, trim_warnings = assemble_video_prompt_ex(shot, refs, seg_no, genre, style_suffix)
        warnings = speaker_warnings(shot, refs) + shot_size_warnings([shot]) + beat_rhythm_warnings([shot]) + speech_overflow_warnings([shot]) + fx_boundary_warnings([shot]) + trim_warnings
    else:
        prompt = shot.get("video_prompt") or shot.get("prompt", "") or ""
        warnings = []
    warnings = warnings + form_warnings(refs)
    return {"files": [r["path"] for r in refs], "refs": refs, "prompt": prompt, "warnings": warnings}
