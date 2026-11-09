"""风格分类库：定义项目风格，贯穿小说生成、角色/道具/场景提取、分镜文生图全链路"""

# 预置风格分类
STYLE_LIBRARY = [
    {
        "id": "xuanhuan",
        "name": "玄幻",
        "genre": "玄幻",
        "description": "上古大能、龙血觉醒、境界突破，少年逆天改命",
        "art_style": "Chinese fantasy epic, majestic xianxia atmosphere, glowing spiritual energy effects, golden dragon aura, ancient oriental temples and mountains, dramatic godly lighting, cinematic composition, high detail",
        "character_tone": "神采奕奕、仙气凛然、衣袂飘飘、眼神锐利，气质超凡脱俗，周身或有灵光",
        "scene_tone": "云雾缭绕的仙山、宏伟古殿、瀑布灵潭、灵气光效，色彩瑰丽而神圣"
    },
    {
        "id": "mojueshi",
        "name": "末世废土",
        "genre": "末世",
        "description": "废土求生、丧尸横行、资源匮乏、人性挣扎",
        "art_style": "apocalyptic wasteland, ruined city ruins, desaturated cold gray tones, dust and debris, harsh survival atmosphere, dramatic dark lighting, cinematic composition, gritty realism",
        "character_tone": "衣衫褴褛、满脸风霜、眼神疲惫而坚毅，身上有尘土与伤痕",
        "scene_tone": "坍塌的楼宇、锈蚀的车辆、荒芜的废墟、灰暗压抑的天空，冷色调"
    },
    {
        "id": "dushi",
        "name": "都市",
        "genre": "都市",
        "description": "现代都市职场、情感、逆袭、商战",
        "art_style": "modern urban, sleek city skyscrapers, clean contemporary architecture, city night neon lighting, cinematic composition, polished realism",
        "character_tone": "衣着得体、职业干练、气质现代，眼神或沉稳或锐利",
        "scene_tone": "高楼大厦、玻璃幕墙、夜晚霓虹、办公室、街道车流，现代明快"
    },
    {
        "id": "xianxia",
        "name": "仙侠",
        "genre": "仙侠",
        "description": "御剑飞行、修仙问道、门派恩怨、渡劫飞升",
        "art_style": "celestial immortal cultivation, flying swords, flowing white robes, misty immortal mountains, ethereal qi energy, soft divine light, Chinese ink painting elegance, cinematic composition",
        "character_tone": "仙风道骨、清冷出尘、衣袂飘飞、眉目如画，气质空灵",
        "scene_tone": "云雾仙山、瀑布、竹林、道观、星辰夜空，空灵缥缈、青白配色"
    },
    {
        "id": "xuanyi",
        "name": "悬疑",
        "genre": "悬疑",
        "description": "烧脑推理、迷雾重重、暗藏玄机、真相揭晓",
        "art_style": "noir thriller, dark moody atmosphere, deep shadows, dramatic chiaroscuro lighting, tense suspense, muted cold palette, cinematic composition",
        "character_tone": "神色凝重、眼神深邃、着装低调，气质神秘而警觉",
        "scene_tone": "昏暗的旧宅、雨夜街道、案发现场、光影交错，压抑的暗色调"
    },
    {
        "id": "gaoxiao",
        "name": "轻松搞笑",
        "genre": "搞笑",
        "description": "轻松明快、诙谐幽默、生活化、反转笑点",
        "art_style": "light-hearted comedy, bright cheerful colors, warm sunlight, playful exaggerated expressions, clean cartoon-realistic blend, lively composition",
        "character_tone": "表情夸张、神态生动、衣着明快，气质亲和可爱",
        "scene_tone": "明亮的生活场景、暖色调、阳光、街道店铺，轻快活泼"
    },
    {
        "id": "gufeng",
        "name": "古风权谋",
        "genre": "古风",
        "description": "古代朝堂、江湖恩怨、权谋博弈、家国天下",
        "art_style": "ancient Chinese court drama, majestic palace architecture, flowing hanfu robes, intricate silk textures, warm antique palette, cinematic composition, high detail",
        "character_tone": "雍容华贵、举止端方、眉目含威，衣冠楚楚、气质内敛",
        "scene_tone": "巍峨宫殿、红墙金瓦、亭台楼阁、江湖客栈，古色古香"
    }
]


def get_style_by_id(style_id: str) -> dict:
    """根据风格ID获取风格定义"""
    for s in STYLE_LIBRARY:
        if s["id"] == style_id:
            return s
    return None


def get_style_name(style_id: str) -> str:
    """获取风格显示名称"""
    s = get_style_by_id(style_id)
    return s["name"] if s else style_id


def build_style_art_prompt(style_id: str) -> str:
    """构建用于文生图的风格绘画指令（英文）"""
    s = get_style_by_id(style_id)
    if s:
        return s["art_style"]
    # 自定义风格：直接返回空，不强制风格
    return ""


def build_style_character_tone(style_id: str) -> str:
    """构建角色描述的风格倾向（中文）"""
    s = get_style_by_id(style_id)
    if s:
        return s["character_tone"]
    return ""


def build_style_scene_tone(style_id: str) -> str:
    """构建场景描述的风格倾向（中文）"""
    s = get_style_by_id(style_id)
    if s:
        return s["scene_tone"]
    return ""


def build_style_block(style_id: str) -> str:
    """构建提示词中注入的风格段落（用于角色/道具/场景提取）"""
    if not style_id:
        return ""
    s = get_style_by_id(style_id)
    if not s:
        return f"【风格倾向】{style_id}"
    return (
        f"【作品风格】{s['name']}风格\n"
        f"【角色形象倾向】{s['character_tone']}\n"
        f"【场景氛围倾向】{s['scene_tone']}\n"
        f"【绘画风格指令】{s['art_style']}"
    )


# 真人实拍类风格的判断。题材库任务合并后改为读风格定义里的字段（s["realistic"]），调用方不变。
_REALISTIC_KEYWORDS = ("realistic", "real_person", "live_action", "真人", "实拍")


def is_realistic_style(style_id: str) -> bool:
    """风格是否为真人实拍类：预置风格看 realistic 字段或 id / 名称，自定义风格看文字本身。"""
    if not style_id:
        return False
    s = get_style_by_id(style_id)
    if s and s.get("realistic") is not None:
        return bool(s["realistic"])
    blob = " ".join(str(x) for x in ((style_id, s.get("name")) if s else (style_id,)) if x).lower()
    return any(k in blob for k in _REALISTIC_KEYWORDS)


def build_extract_style_block(style_id: str) -> str:
    """资产提取用的风格段落：普通风格段落 + 真人类风格追加的面部真实质感要求。"""
    from core.prompt_tpl import REALISTIC_FACE_NOTE

    block = build_style_block(style_id)
    if is_realistic_style(style_id):
        block = f"{block}\n{REALISTIC_FACE_NOTE}" if block else REALISTIC_FACE_NOTE
    return block


def build_genre_rhythm(genre: str = None, style_id: str = None) -> str:
    """按项目题材取叙事节奏段落（novel/shot 共用）。

    优先级：项目 genre → 所选风格的 genre → 通用。项目 genre 是自由文本且匹配不到时，回退风格的 genre。
    """
    from core.genre_rhythm import match_genre, get_genre_rhythm_text, GENERAL_GENRE
    candidates = [genre]
    style = get_style_by_id(style_id) if style_id else None
    if style:
        candidates.append(style.get("genre"))
    for g in candidates:
        if g and match_genre(g) != GENERAL_GENRE:
            return get_genre_rhythm_text(g)
    return get_genre_rhythm_text(GENERAL_GENRE)
