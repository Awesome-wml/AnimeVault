"""T-213：润色与转剧本的表演层、题材爽点清单、新题材匹配（纯模板断言，不连库）。"""
from api.script import build_script_prompts
from core.genre_rhythm import GENERAL_GENRE, GENRE_RHYTHM, get_genre_rhythm_text, match_genre
from core.llm_factory import safe_format
from core.prompt_tpl import NOVEL_POLISH_PROMPT, PERFORMANCE_RULES, SCRIPT_CONVERT_PROMPT
from core.style_library import GENRES, build_genre_rhythm

PERF_EXAMPLES = ["攥紧衣角欲言又止", "红了眼眶把杯子重重一放", "把脸一沉冷哼一声",
                 "蹲在门口闷头不吭声", "翻着白眼阴阳怪气", "颤抖着手指向门口"]


def test_performance_rules_content():
    assert PERFORMANCE_RULES.startswith("【表演层】")
    for ex in PERF_EXAMPLES:
        assert ex in PERFORMANCE_RULES
    for snd in ("雨声", "杯底碰桌", "远处喇叭"):
        assert snd in PERFORMANCE_RULES
    assert "口语化" in PERFORMANCE_RULES and "书面腔" in PERFORMANCE_RULES
    # 底线不放松：对白沿用原话、不加事实；不加规避原创检测的要求
    assert "沿用原话" in PERFORMANCE_RULES and "不添加原文没有的事实" in PERFORMANCE_RULES
    assert "{" not in PERFORMANCE_RULES and "}" not in PERFORMANCE_RULES


def test_polish_and_convert_share_performance_rules():
    for tpl in (NOVEL_POLISH_PROMPT, SCRIPT_CONVERT_PROMPT):
        assert PERFORMANCE_RULES in tpl
        assert "重复率" not in tpl and "连续6个字" not in tpl
    # 润色：表演层不算加戏，但不能新增事实；自检查爆点的微表情
    assert "表演层只加“怎么演”" in NOVEL_POLISH_PROMPT
    assert "每个情绪爆点是否都有至少一处微表情或肢体动作" in NOVEL_POLISH_PROMPT
    assert "对白意思不变，只按需要拆短" in NOVEL_POLISH_PROMPT
    # 转剧本：action 必须有微表情/肢体动作，beat 写情绪起伏，自检每场 action；对白仍逐字沿用
    assert "每场 action 必须包含微表情和肢体动作，不许只写站位和环境" in SCRIPT_CONVERT_PROMPT
    assert "beat 写本场情绪起伏" in SCRIPT_CONVERT_PROMPT
    assert "每场 action 至少有一处微表情或肢体动作" in SCRIPT_CONVERT_PROMPT
    assert "对白沿用原话：保留下来的对白逐字沿用小说原文" in SCRIPT_CONVERT_PROMPT
    assert "不要把叙述改写成对白" in SCRIPT_CONVERT_PROMPT
    # JSON 示例里的 action 本身就带微表情，beat 带情绪起伏
    assert "指节攥得发白" in SCRIPT_CONVERT_PROMPT and "乙从镇定到指尖发抖" in SCRIPT_CONVERT_PROMPT


def test_polish_prompt_renders_with_performance_and_hooks():
    prompt = safe_format(NOVEL_POLISH_PROMPT, novel_text="原文一句。", person_rule="保持原文人称",
                         genre_rhythm=build_genre_rhythm("家庭伦理", "dushi"))
    assert "【表演层】" in prompt and "【题材节奏：家庭伦理】" in prompt and "爽点清单" in prompt
    assert "{" not in prompt.split("【小说原文】")[0]


def test_every_genre_has_highlight_list():
    for key, lines in GENRE_RHYTHM.items():
        hits = [l for l in lines if l.startswith("爽点清单：")]
        assert len(hits) == 1, key
        assert len(hits[0]) > 30, key
    assert "婆媳正面对峙" in get_genre_rhythm_text("家庭伦理")
    assert "身份反差" in get_genre_rhythm_text("都市") and "众人态度集体反转" in get_genre_rhythm_text("都市")
    assert "爽点清单" in get_genre_rhythm_text("不存在的题材")
    assert "爽点清单" in get_genre_rhythm_text(GENERAL_GENRE)


def test_match_genre_new_genres_and_aliases():
    for g in ("家庭伦理", "甜宠虐恋", "职场", "重生逆袭"):
        assert g in GENRE_RHYTHM and match_genre(g) == g
    assert match_genre("真人·家庭伦理") == "家庭伦理"
    assert match_genre("婆媳大战") == "家庭伦理"
    assert match_genre("都市甜宠") == "甜宠虐恋"
    assert match_genre("霸总虐恋") == "甜宠虐恋"
    assert match_genre("现实职场") == "职场"
    assert match_genre("都市职场") == "职场"
    assert match_genre("都市商战") == "职场"
    assert match_genre("重生") == "重生逆袭"
    assert match_genre("3DGC重生逆袭") == "重生逆袭"
    assert match_genre("穿越逆袭") == "重生逆袭"
    # 旧行为不变
    assert match_genre("都市言情") == "都市"
    assert match_genre("玄幻修仙") == "玄幻"
    assert match_genre("古风权谋") == "古风"
    assert match_genre("") == GENERAL_GENRE and match_genre(None) == GENERAL_GENRE
    # 预置题材的 genre 键全部精确命中
    for s in GENRES:
        assert match_genre(s["genre"]) == s["genre"]


def test_build_genre_rhythm_hits_new_genres():
    # 项目题材是新题材、风格是都市：优先项目题材
    assert "【题材节奏：家庭伦理】" in build_genre_rhythm("家庭伦理", "dushi")
    assert "【题材节奏：职场】" in build_genre_rhythm("职场逆袭", "dushi")
    assert "【题材节奏：甜宠虐恋】" in build_genre_rhythm("甜宠虐恋", None)
    assert "【题材节奏：重生逆袭】" in build_genre_rhythm("重生逆袭", "xuanhuan")
    # 题材匹配不上时回退旧风格 id 对应的题材
    assert "【题材节奏：都市】" in build_genre_rhythm("随便写的", "dushi")
    # 新项目：媒介 + 题材
    assert "【题材节奏：家庭伦理】" in build_genre_rhythm(genre="家庭伦理", medium="realistic")


def test_script_prompt_injects_performance_and_highlights():
    [(_, render)] = build_script_prompts("script_convert", None, "第一段。" * 30, style_block="",
                                         genre_rhythm=build_genre_rhythm("都市", "dushi"), person="keep",
                                         target_seconds=120, chunk_chars=4000)
    prompt = "\n".join(m["content"] for m in render(None))
    assert "【表演层】" in prompt and "爽点清单：身份反差揭晓" in prompt
    # 表演层段落紧跟题材节奏之后、台词分类之前（改编原则里只是引用了它）
    assert prompt.index("【题材节奏：都市】") < prompt.index("\n【表演层】\n") < prompt.index("【台词分类")
