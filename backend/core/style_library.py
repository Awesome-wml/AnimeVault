"""风格库：媒介（真人实拍 / 3D 国漫 / 2D 动漫）与题材两个维度，贯穿小说生成、资产提取、三视图、分镜文生图全链路。

- 媒介 MEDIUMS：决定画风词（art_style，直接进文生图提示词）、视频风格后缀（video_suffix）和是否真人（realistic）。
  2D 动漫下有古风厚涂 / 日系赛璐璐 / 现代国漫三个子风格，各算一个媒介 id，group 同为 "2d"。
- 题材 GENRES：决定角色形象倾向、场景氛围倾向、色调氛围词（art_tone）和叙事节奏（genre_rhythm，按 genre 键取）。
- 项目保存 medium + genre；旧项目只有 style（7 个旧风格 id）时按 LEGACY_STYLES 映射为 (medium=3D 国漫, genre=原题材)。

直接发给出图模型的文字（art_style / art_tone / video_suffix）不能含“裸露/内衣/走光/暴露/血腥”这类词：智谱过滤只看关键词不看否定（1301），
backend/tests/test_image_prompt_safety.py 有断言。
"""

DEFAULT_MEDIUM = "cg3d"
DEFAULT_2D_MEDIUM = "2d_guoman"

# 媒介大类（前端第一行三张卡）：2D 动漫下再选子风格
MEDIUM_GROUPS = [
    {"id": "realistic", "name": "真人实拍", "description": "电影级写实质感，真实皮肤与自然光影，像真人短剧一样可信"},
    {"id": "cg3d", "name": "3D 国漫", "description": "国漫 3D 渲染，细腻材质与电影级光影，当下漫剧的主流画面"},
    {"id": "2d", "name": "2D 动漫", "description": "手绘动画质感，可选古风厚涂、日系赛璐璐、现代国漫三种画风"},
]

MEDIUMS = [
    {
        "id": "realistic",
        "group": "realistic",
        "name": "真人实拍",
        "description": "电影级写实质感，真实皮肤与自然光影，像真人短剧一样可信",
        "realistic": True,
        "art_style": "真人实拍电影级写实质感，真实皮肤毛孔与肤色细节，自然光影与真实景深，服装面料质感真实，不美颜、不偶像化、不卡通化",
        "video_suffix": "真人实拍电影级写实质感，自然写实光影，真实皮肤质感，电影级色调",
    },
    {
        "id": "cg3d",
        "group": "cg3d",
        "name": "3D 国漫",
        "description": "国漫 3D 渲染，细腻材质与电影级光影，当下漫剧的主流画面",
        "realistic": False,
        "art_style": "国漫 3D 渲染，细腻的皮肤、发丝与布料材质，精致五官，电影级光影，画面干净通透",
        "video_suffix": "3D 国漫风格，细腻材质，电影级光影，电影级色调，画质 4K 超清",
    },
    {
        "id": "2d_gufeng",
        "group": "2d",
        "name": "古风厚涂",
        "description": "工笔线稿加水墨晕染与厚重色块，东方写意意境",
        "realistic": False,
        "art_style": "2D 国漫古风厚涂画风，工笔线稿勾勒轮廓，水墨晕染与厚重色块结合，东方写意意境，沉稳的东方色调与柔和光影",
        "video_suffix": "2D 古风厚涂风格，工笔线稿与水墨晕染结合，东方写意意境，沉稳东方色调，柔和光影",
    },
    {
        "id": "2d_cel",
        "group": "2d",
        "name": "日系赛璐璐",
        "description": "干净线条、纯色平涂、明亮清新的日系动画画面",
        "realistic": False,
        "art_style": "2D 日系赛璐璐动画画风，干净利落的线条，纯色平涂，明亮清新的配色，清透光影",
        "video_suffix": "2D 日系赛璐璐画风，干净线条，纯色平涂，明亮色彩，清新光影，电影级色调",
    },
    {
        "id": "2d_guoman",
        "group": "2d",
        "name": "现代国漫",
        "description": "流畅线条、现代配色、动态感强的国产动画画风",
        "realistic": False,
        "art_style": "2D 现代国漫画风，流畅线条，现代配色，动态感强，光影自然",
        "video_suffix": "2D 现代国漫画风，流畅线条，现代配色，动态感强，光影自然，电影级色调",
    },
]

# 题材：id 与旧风格 id 一致（旧 style 映射时直接复用），genre 是 genre_rhythm.GENRE_RHYTHM 的键
GENRES = [
    {
        "id": "xuanhuan",
        "name": "玄幻",
        "genre": "玄幻",
        "description": "境界突破、打脸天才、夺宝奇遇，少年逆天改命",
        "character_tone": "主角少年英气或仙风道骨，眼神锐利、神采飞扬，周身或有灵光；反派魔气森森、倨傲阴鸷；服饰以仙袍、道袍、灵甲为主，飘逸华丽、纹饰考究",
        "scene_tone": "仙山、宗门广场、洞府秘境、天宫药园，云雾缭绕、灵气氤氲，宏大壮丽，色彩瑰丽而神圣",
        "art_tone": "仙气飘渺的瑰丽色调，宏大气氛，灵气光效点缀",
    },
    {
        "id": "mojueshi",
        "name": "末世废土",
        "genre": "末世",
        "description": "废土求生、资源争夺、人性抉择，绝境里的互助与背叛",
        "character_tone": "主角坚韧果敢、满脸风霜，眼神疲惫而警觉；反派或变异体狰狞可怖；衣物破旧战损、沾满尘土，以实用装备和临时拼凑的护具为主",
        "scene_tone": "废弃都市、破败街道、避难所、荒野废墟，坍塌楼宇与锈蚀车辆，灰暗压抑的天空，荒凉冷色调",
        "art_tone": "灰暗废土色调，荒凉末日氛围，残破冷硬的光影",
    },
    {
        "id": "dushi",
        "name": "都市",
        "genre": "都市",
        "description": "身份反差、隐藏底牌、商战逆袭，现代都市里的翻盘",
        "character_tone": "主角平凡外表下藏着底牌，衣着得体、职业干练，眼神沉稳或锐利；反派嚣张或精明；穿搭现代时尚，贴合身份地位",
        "scene_tone": "写字楼、玻璃幕墙、豪宅会所、街头车流、夜晚霓虹，现代冷峻与明快并存，有都市质感",
        "art_tone": "现代都市色调，霓虹与冷白光影交错，干净利落的氛围",
    },
    {
        "id": "xianxia",
        "name": "仙侠",
        "genre": "仙侠",
        "description": "御剑飞行、修仙问道、门派恩怨、渡劫飞升",
        "character_tone": "仙风道骨、清冷出尘，眉目如画、衣袂飘飞，气质空灵；反派邪气外露却仍有仙门气度；服饰以广袖长袍、道袍、发冠为主，青白素色",
        "scene_tone": "云海仙山、瀑布竹林、道观剑冢、星辰夜空，空灵缥缈，青白配色，留白与雾气营造意境",
        "art_tone": "空灵缥缈的青白色调，云雾意境，柔和仙光",
    },
    {
        "id": "xuanyi",
        "name": "悬疑",
        "genre": "悬疑",
        "description": "烧脑推理、迷雾重重、层层反转，真相在最后揭开",
        "character_tone": "主角沉着敏锐、神色凝重、眼神深邃；嫌疑人各有藏不住的小动作；着装低调，灰暗冷色，气质神秘而警觉",
        "scene_tone": "旧宅、雨夜街道、废弃医院、雾中荒村、案发现场，昏暗压抑，光影交错，冷色暗调",
        "art_tone": "暗调冷色，阴郁压抑的氛围，暗部侧光与前景遮挡",
    },
    {
        "id": "gaoxiao",
        "name": "轻松搞笑",
        "genre": "搞笑",
        "description": "无厘头笑点、反差萌、沙雕反转，轻松明快的生活喜剧",
        "character_tone": "表情丰富夸张、神态生动，反差萌和喜剧辨识度强；反派蠢萌或滑稽；穿搭色彩明快、造型略带夸张但仍是日常衣着",
        "scene_tone": "日常生活场景、夸张道具场景、脑洞场景，明亮活泼、色彩鲜艳，阳光与暖色为主",
        "art_tone": "明亮活泼的高饱和色调，夸张搞怪的氛围，俏皮光影",
    },
    {
        "id": "gufeng",
        "name": "古风权谋",
        "genre": "古风",
        "description": "宫斗宅斗、位分争夺、权谋博弈，一句话里藏杀机",
        "character_tone": "主角端庄大气或外柔内刚，举止端方、眉目含威；反派表面华贵内里狠毒；服饰贴合宫廷与世家规制，凤袍、襦裙、广袖、云肩、步摇珠翠，形制考究",
        "scene_tone": "正殿寝宫、御花园、冷宫、宫宴大殿、长廊庭院、深宅大院，红墙金瓦、暖金宫灯，雍容华贵、端庄威仪",
        "art_tone": "暖金宫廷色调，华贵烛光氛围，古装华美质感",
    },
    {
        "id": "jiating",
        "name": "家庭伦理",
        "genre": "家庭伦理",
        "description": "婆媳冲突、偏心父母、极品亲戚，饭桌上的憋屈与爆发",
        "character_tone": "人物年龄感真实、生活气息浓，婆婆、儿媳、丈夫、亲戚各有鲜明性格与神态；穿搭生活化写实，居家服、买菜装、旧外套，细节带生活痕迹",
        "scene_tone": "客厅、厨房、卧室、楼道、小区、菜市场，烟火气十足，家具陈设真实，暖黄灯光与日常杂物并存",
        "art_tone": "生活化烟火气，自然写实光影，温暖而真实的家庭色调",
    },
    {
        "id": "tianchong",
        "name": "甜宠虐恋",
        "genre": "甜宠虐恋",
        "description": "甜宠互动、虐心拉扯、破镜重圆，心动与心碎交替",
        "character_tone": "男主深情霸道或温柔克制，女主甜美灵动或坚韧独立，两人站在一起有 CP 感；配角情敌精致有攻击性；穿搭时尚精致，贴合都市精英与少女感",
        "scene_tone": "都市公寓、高档餐厅、公司办公室、海边、雨夜街头、浪漫约会地，柔光暖调为主，虐心段落转冷色雨夜",
        "art_tone": "温馨浪漫的柔光暖调，心动氛围，虐心段落转为冷调雨夜",
    },
    {
        "id": "zhichang",
        "name": "现实职场",
        "genre": "职场",
        "description": "功劳被抢、当众背锅、升职逆袭，用证据和专业打脸",
        "character_tone": "主角职场精英感或草根逆袭气质，眼神专注坚定；反派上司或同事形象鲜明、精于算计；穿搭职业装、正装、通勤装，整洁得体",
        "scene_tone": "写字楼、开放办公区、会议室、茶水间、电梯间，现代商务氛围，冷白灯光与玻璃隔断，整洁而有压力感",
        "art_tone": "现代商务色调，冷白职场光影，整洁写实的氛围",
    },
    {
        "id": "chongsheng",
        "name": "重生逆袭",
        "genre": "重生逆袭",
        "description": "带着前世记忆回到关键一天，先手布局、步步翻盘",
        "character_tone": "主角重生后睿智果敢、眼神笃定，与前世的隐忍形成反差；反派前世嚣张今世节节败退；服饰随身份逆袭逐步升级，从朴素到体面",
        "scene_tone": "豪门宅邸、公司、家族老宅、校园或宅院，按剧情从压抑逼仄转向开阔明亮，前世回忆偏冷、当下偏暖",
        "art_tone": "逆袭爽感色调，前世冷调与当下暖调对照，光影自然",
    },
]

# 旧风格 id → 题材 id（旧项目只有 style 字段时，媒介默认 3D 国漫）
LEGACY_STYLES = {"xuanhuan": "xuanhuan", "mojueshi": "mojueshi", "dushi": "dushi", "xianxia": "xianxia",
                 "xuanyi": "xuanyi", "gaoxiao": "gaoxiao", "gufeng": "gufeng"}

_REALISTIC_KEYWORDS = ("realistic", "real_person", "live_action", "真人", "实拍")


def get_medium(medium_id: str) -> dict:
    """按媒介 id 取定义；传媒介大类 id（如 "2d"）时取该类的默认子风格。"""
    if not medium_id:
        return None
    for m in MEDIUMS:
        if m["id"] == medium_id:
            return m
    if medium_id == "2d":
        return get_medium(DEFAULT_2D_MEDIUM)
    return None


def get_genre(genre: str) -> dict:
    """按题材 id / 名称 / 节奏键精确取定义，取不到时按 genre_rhythm 的别名匹配（“婆媳”→家庭伦理、“都市商战”→职场）。"""
    g = (genre or "").strip()
    if not g:
        return None
    for d in GENRES:
        if g in (d["id"], d["name"], d["genre"]):
            return d
    from core.genre_rhythm import match_genre, GENERAL_GENRE
    key = match_genre(g)
    if key != GENERAL_GENRE:
        for d in GENRES:
            if d["genre"] == key:
                return d
    return None


def resolve_style(medium: str = None, genre: str = None, style_id: str = None) -> dict:
    """把项目的 medium / genre / 旧 style 解析成 {"medium": 媒介定义或 None, "genre": 题材定义或 None, "custom": 自定义文字}。

    - medium 位置也接受旧 style id（调用方只有一个字符串时直接传进来）。
    - 旧 style id：媒介缺省为 3D 国漫，题材缺省为该风格对应的题材。
    - 都不认识的文字算自定义风格：进 custom，并尝试按别名匹配题材。
    """
    m_def = get_medium(medium)
    legacy = LEGACY_STYLES.get(style_id or "") or (None if m_def else LEGACY_STYLES.get(medium or ""))
    g_def = get_genre(genre)
    custom = ""
    for text in (style_id, medium):
        if text and not get_medium(text) and text not in LEGACY_STYLES:
            custom = text
            break
    if legacy:
        m_def = m_def or get_medium(DEFAULT_MEDIUM)
        g_def = g_def or get_genre(legacy)
    if custom and not g_def:
        g_def = get_genre(custom)
    return {"medium": m_def, "genre": g_def, "custom": custom}


def style_ref(project: dict = None, **override) -> dict:
    """从项目文档取 (medium, genre, style_id)，请求里显式传的字段优先；结果可直接 ** 展开给 build_* 函数。"""
    p = project or {}
    ref = {"medium": p.get("medium"), "genre": p.get("genre"), "style_id": p.get("style")}
    for k, v in override.items():
        if v:
            ref[k] = v
    return ref


def style_label(medium: str = None, genre: str = None, style_id: str = None) -> str:
    """显示名：“真人实拍 · 家庭伦理”。"""
    r = resolve_style(medium, genre, style_id)
    parts = [d["name"] for d in (r["medium"], r["genre"]) if d]
    return " · ".join(parts) or r["custom"]


def get_style_name(style_id: str) -> str:
    """旧接口：旧风格 id / 自定义文字的显示名。"""
    return style_label(style_id=style_id) or style_id


def build_style_art_prompt(medium: str = None, genre: str = None, style_id: str = None) -> str:
    """文生图用的画风指令（中文）：媒介画风词 + 题材色调氛围词；没有预置媒介时返回自定义文字。"""
    r = resolve_style(medium, genre, style_id)
    m, g = r["medium"], r["genre"]
    if not m:
        return r["custom"]
    return f"{m['art_style']}，{g['art_tone']}" if g else m["art_style"]


def build_video_style_suffix(medium: str = None, genre: str = None, style_id: str = None) -> str:
    """视频提示词末尾的风格后缀（中文）：媒介视频风格 + 题材色调氛围词。"""
    r = resolve_style(medium, genre, style_id)
    m, g = r["medium"], r["genre"]
    if not m:
        return r["custom"]
    return f"{m['video_suffix']}，{g['art_tone']}" if g else m["video_suffix"]


def build_style_character_tone(medium: str = None, genre: str = None, style_id: str = None) -> str:
    """角色描述的题材倾向（中文）。"""
    g = resolve_style(medium, genre, style_id)["genre"]
    return g["character_tone"] if g else ""


def build_style_scene_tone(medium: str = None, genre: str = None, style_id: str = None) -> str:
    """场景描述的题材倾向（中文）。"""
    g = resolve_style(medium, genre, style_id)["genre"]
    return g["scene_tone"] if g else ""


def build_style_block(medium: str = None, genre: str = None, style_id: str = None) -> str:
    """提示词里注入的风格段落（角色/道具/场景提取、转剧本、拆分镜共用）：媒介一段 + 题材一段，全中文。"""
    r = resolve_style(medium, genre, style_id)
    m, g = r["medium"], r["genre"]
    if not m and not g:
        return f"【风格倾向】{r['custom']}" if r["custom"] else ""
    lines = []
    if m:
        lines.append(f"【作品媒介】{m['name']}：{m['description']}")
    if g:
        lines.append(f"【作品题材】{g['name']}：{g['description']}")
        lines.append(f"【角色形象倾向】{g['character_tone']}")
        lines.append(f"【场景氛围倾向】{g['scene_tone']}")
    if m:
        lines.append(f"【画风指令】{build_style_art_prompt(medium, genre, style_id)}")
    return "\n".join(lines)


def is_realistic_style(medium: str = None, style_id: str = None, genre: str = None) -> bool:
    """是否真人实拍类：预置媒介读定义里的 realistic 字段；自定义风格文字按关键词判断。"""
    r = resolve_style(medium, genre, style_id)
    if r["medium"]:
        return bool(r["medium"].get("realistic"))
    return any(k in r["custom"].lower() for k in _REALISTIC_KEYWORDS)


def build_extract_style_block(medium: str = None, genre: str = None, style_id: str = None) -> str:
    """资产提取用的风格段落：普通风格段落 + 真人类媒介追加的面部真实质感要求。"""
    from core.prompt_tpl import REALISTIC_FACE_NOTE

    block = build_style_block(medium, genre, style_id)
    if is_realistic_style(medium, style_id, genre):
        block = f"{block}\n{REALISTIC_FACE_NOTE}" if block else REALISTIC_FACE_NOTE
    return block


def build_genre_rhythm(genre: str = None, style_id: str = None, medium: str = None) -> str:
    """按题材取叙事节奏段落（novel/script/shot 共用）。

    优先级：项目 genre（自由文本，按别名匹配）→ 旧风格 id 对应的题材 → 通用。
    """
    from core.genre_rhythm import match_genre, get_genre_rhythm_text, GENERAL_GENRE
    candidates = [genre]
    g_def = resolve_style(medium, genre, style_id)["genre"]
    if g_def:
        candidates.append(g_def["genre"])
    for g in candidates:
        if g and match_genre(g) != GENERAL_GENRE:
            return get_genre_rhythm_text(g)
    return get_genre_rhythm_text(GENERAL_GENRE)


def style_library_payload() -> dict:
    """给前端风格页的库：媒介大类（含子风格）、平铺媒介、题材。"""
    groups = []
    for grp in MEDIUM_GROUPS:
        subs = [{"id": m["id"], "name": m["name"], "description": m["description"]} for m in MEDIUMS if m["group"] == grp["id"]]
        groups.append({**grp, "mediums": subs})
    return {
        "medium_groups": groups,
        "mediums": [{"id": m["id"], "group": m["group"], "name": m["name"], "description": m["description"],
                     "realistic": m["realistic"]} for m in MEDIUMS],
        "genres": [{"id": g["id"], "name": g["name"], "genre": g["genre"], "description": g["description"]} for g in GENRES],
        "default_medium": DEFAULT_MEDIUM,
        "legacy_styles": LEGACY_STYLES,
    }
