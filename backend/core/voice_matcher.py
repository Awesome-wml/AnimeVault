"""音色匹配引擎

根据角色的结构化切片特征（gender/age_group/trait）从音色库中确定性匹配音色，
并保证同项目内同类角色分配不同音色。
"""
from .providers.tts_provider import DoubaoTTSProvider

# 特质词 → 音色气质标签 的映射（用于打分）
TRAIT_KEYWORDS = {
    "阳刚": ["阳刚", "豪迈", "热血", "爽朗", "硬朗"],
    "阴森": ["阴冷", "邪气", "反派", "威慑", "阴沉"],
    "温柔": ["温柔", "婉转", "知性", "柔和"],
    "阳光": ["阳光", "清朗", "少年感", "活泼", "开朗"],
    "威严": ["威严", "沉稳", "成熟", "厚重", "领导"],
    "清冷": ["清冷", "冷峻", "孤高", "仙气"],
    "憨厚": ["憨厚", "朴实", "醇厚", "木讷"],
    "妖媚": ["妖媚", "魅惑", "勾人"],
    "苍老": ["苍老", "长者", "慈祥", "暮年"],
    "活泼": ["活泼", "甜美", "俏皮", "灵动"],
    "醇厚": ["醇厚", "磁性", "低沉", "稳重"],
    "灵动": ["灵动", "清新", "活泼"],
}

# 音色库（带元数据）
def get_voice_library():
    return DoubaoTTSProvider(api_key="dummy").get_available_voices()


def _normalize_age(age_group: str) -> str:
    """归一化年龄段"""
    g = (age_group or "").strip()
    for key in ("少年", "青年", "中年", "暮年"):
        if key in g:
            return key
    return "青年"  # 默认


def _score_voice(voice: dict, gender: str, age_group: str, trait: str) -> int:
    """计算音色与角色切片的匹配分"""
    score = 0
    # 1. 性别必须匹配（不匹配直接 0 分淘汰）
    if voice.get("gender") != gender:
        return 0

    # 2. 年龄段匹配（关键）
    voice_age = voice.get("age_group", "")
    if voice_age == age_group:
        score += 100

    # 3. 特质匹配（加分项）
    if trait:
        for kw, tags in TRAIT_KEYWORDS.items():
            if kw in trait or trait in kw:
                # 特质词命中 → 看音色 tags 里是否有相关标签
                vtags = [str(t) for t in voice.get("tags", [])]
                overlap = set(tags) & set(vtags)
                if overlap:
                    score += 40 + 10 * len(overlap)
                else:
                    score += 15
                break
        # trait 直接命中音色 tone/tags
        vtags = [str(t) for t in voice.get("tags", [])]
        vtone = voice.get("tone", "")
        if trait in vtags or trait in vtone:
            score += 30

    # 4. tone 中的特质词也加分
    vtone = voice.get("tone", "")
    for kw in TRAIT_KEYWORDS:
        if kw in vtone and (kw in (trait or "")):
            score += 10

    return score


def match_voices(characters: list, used_voices: set = None) -> list:
    """为角色列表确定性匹配音色。

    Args:
        characters: 角色列表，每个含 name/gender/age_group/trait/importance
        used_voices: 已占用的音色集合（跨批次去重用）

    Returns:
        list[dict]: [{name, voice, reason}, ...] 按原顺序
    """
    library = get_voice_library()
    used = set(used_voices or [])

    # 先按重要性排序：main 优先匹配（保证主角音色独特）
    importance_order = {"main": 0, "support": 1, "extra": 2}

    # 需要配音的角色（main/support），extra 跳过
    need = [c for c in characters if (c.get("importance") or "support") in ("main", "support")]
    need_sorted = sorted(need, key=lambda c: importance_order.get(c.get("importance"), 1))

    assigned = []
    # 记录每个音色已被哪类角色占用，用于同类去重
    for char in need_sorted:
        gender = char.get("gender") or _infer_gender(char.get("description", ""))
        age_group = _normalize_age(char.get("age_group"))
        trait = char.get("trait") or _infer_trait(char.get("description", ""))

        # 候选：性别匹配的，按分数排序，优先未使用的
        scored = []
        for v in library:
            if v.get("gender") != gender:
                continue
            s = _score_voice(v, gender, age_group, trait)
            if s > 0:
                scored.append((s, v))
        scored.sort(key=lambda x: -x[0])

        # 选一个：优先未用过的，否则用分数最高的（允许次要复用）
        chosen = None
        for s, v in scored:
            if v["name"] not in used:
                chosen = v
                break
        if chosen is None and scored:
            chosen = scored[0][1]  # 全被占用时取分数最高（复用）

        if chosen:
            used.add(chosen["name"])
            assigned.append({
                "name": char["name"],
                "voice": chosen["name"],
                "display_name": chosen["display_name"],
                "reason": f"匹配{gender}·{age_group}·{trait}"
            })
        else:
            assigned.append({
                "name": char["name"],
                "voice": None,
                "display_name": None,
                "reason": "无合适音色"
            })

    return assigned


def _infer_gender(description: str) -> str:
    """从描述推断性别"""
    desc = description or ""
    male_hint = ["他", "少年", "男人", "青年男子", "公子", "爷", "族长", "老者"]
    female_hint = ["她", "少女", "女子", "姑娘", "小姐", "夫人", "老妪"]
    for h in male_hint:
        if h in desc:
            return "male"
    for h in female_hint:
        if h in desc:
            return "female"
    return "male"


def _infer_trait(description: str) -> str:
    """从描述推断特质"""
    desc = description or ""
    for kw in TRAIT_KEYWORDS:
        if kw in desc:
            return kw
    return ""
