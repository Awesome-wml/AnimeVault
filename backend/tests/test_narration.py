"""旁白风格（core/narration）：剧情动漫只在切入点留旁白，对白不动，段时长和小镜头不动。"""
from core import narration as N
from core import shot_split as SS
from core.shot_timing import normalize_segment
from core.video_models import get_video_model

MODEL = get_video_model()


def _seg(lines, beats, **kw):
    raw = SS.expand_segment({"scene": "暴雨青石老巷，深夜", "pos": "沈砚在左，黑衣人在右", "mood": "肃杀",
                             "sound": "密集雨声", "lines": lines, "beats": beats, **kw}, {"沈砚", "黑衣人"})
    return normalize_segment(raw, MODEL)[0][0]


def _alley():
    return _seg(
        ["旁白：刀锋贴着沈砚的耳畔划过，冰冷的触感让他睫毛微颤。", "旁白：他没躲，反手将短匕刺入了对方咽喉。",
         "旁白：暴雨如注，冲刷着青石板缝隙里积攒了百年的苔藓，也将那抹暗红晕染开来。"],
        ["特写|沈砚左侧|侧脸与刀锋|固定|刀锋贴着沈砚耳畔划过，睫毛微颤|眼神不动|1",
         "中近景|两人侧面|沈砚与黑衣人|固定|沈砚反手将短匕刺入黑衣人咽喉|咬肌绷紧|2",
         "特写|贴地低机位|青石板缝与苔藓|固定|暴雨冲刷青石板缝隙里的苔藓|无|3",
         "远景|高处俯拍|整条雨巷|缓慢下降|沈砚站在倒地的黑衣人旁|无|3"])


def test_drama_keeps_only_entry_point_narration():
    seg = _alley()
    dur, beat_times = seg["duration"], [(b["start"], b["end"]) for b in seg["beats"]]
    cut = N.trim_narration(seg, "drama", closing=True)
    texts = [ln["text"] for ln in seg["lines"]]
    assert texts == ["他没躲", "也将那抹暗红晕染开来。"], texts
    assert [ln.get("cue") for ln in seg["lines"]] == ["mind", "close"]
    assert cut == 3 and len(seg["cut_lines"]) == 3 and seg["cut_lines"][0]["kept"] == ""
    assert seg["duration"] == dur and [(b["start"], b["end"]) for b in seg["beats"]] == beat_times   # 时长和小镜头不动
    assert sum(N.speech_seconds(t) for t in texts) <= dur / 3
    # 小镜头的台词序号跟着新列表走：第 1 个小镜头没有旁白了，第 2 个挂“他没躲”
    assert [b["line_refs"] for b in seg["beats"]] == [[], [1], [2], []]
    assert "他没躲" not in seg["video_prompt"] and "台词①" in seg["video_prompt"]            # 【画面】只写序号
    assert seg["narration_style"] == "drama"
    for ln in seg["lines"]:                                                                  # 留下的旁白时间落在原句的时间里
        assert 0 <= ln["start"] < ln["end"] <= dur


def test_segment_without_entry_point_has_no_narration():
    seg = _seg(["旁白：黑衣人捂着颈侧倒下，尘土混着雨水缓缓落下。"],
               ["中景|侧面|黑衣人全身|固定|黑衣人捂着颈侧倒下|无|1", "特写|低机位|地面|固定|尘土混着雨水落下|无|1"])
    assert N.trim_narration(seg, "drama") == 1 and seg["lines"] == [] and seg["beats"][0]["line_refs"] == []
    assert "画面中人物不开口说话" in seg["video_prompt"]


def test_dialogue_is_never_touched_and_full_style_changes_nothing():
    lines = ["旁白：雨越下越大，沈砚握紧了刀。", "黑衣人：这就是你要找的？", "沈砚（心声）：果然是他。"]
    beats = ["近景|正面|沈砚头肩|固定|沈砚握紧刀柄|无|1", "近景|正面|黑衣人头肩|固定|黑衣人抬眼|冷笑|2,3"]
    seg = _seg(lines, beats)
    N.trim_narration(seg, "drama")
    assert [(ln["speaker"], ln["text"]) for ln in seg["lines"]] == [("黑衣人", "这就是你要找的？"), ("沈砚", "果然是他。")]
    assert [b["line_refs"] for b in seg["beats"]] == [[], [1, 2]]
    full = _seg(lines, beats)
    before = [dict(ln) for ln in full["lines"]]
    assert N.trim_narration(full, "full") == 0 and full["lines"] == before and "cut_lines" not in full
    assert N.style_key("") == "drama" and N.style_key("没有这种") == "drama" and N.style_key("FULL") == "full"


def test_opening_and_time_jump_are_entry_points():
    seg = _seg(["旁白：三年后，深夜的青州城下着雨。", "旁白：沈砚推开了酒肆的门。"],
               ["远景|高处|城门与雨幕|固定|雨幕笼罩城楼|无|1", "中景|门口|沈砚背影|跟拍|沈砚推开酒肆的门|无|2"])
    N.trim_narration(seg, "drama", opening=True)
    assert [(ln["text"], ln["cue"]) for ln in seg["lines"]] == [("三年后，深夜的青州城下着雨。", "jump")]   # 整句够短：不拆碎
    assert seg["cut_lines"][0]["kept"] == "" and seg["cut_lines"][0]["text"].startswith("沈砚推开")                      # “沈砚推开了酒肆的门”画面在演，不念


def test_model_choice_wins_but_still_obeys_budget_and_must_be_verbatim():
    seg = _alley()
    N.trim_narration(seg, "drama", keep=["冰冷的触感让他睫毛微颤", "他根本不怕"])     # 第二句不是原文：不认
    assert [ln["text"] for ln in seg["lines"]] == ["冰冷的触感让他睫毛微颤。"]
    seg = _alley()
    N.trim_narration(seg, "drama", keep=[])                                             # 模型说一句都不留
    assert seg["lines"] == []
    seg = _alley()
    seg["keep_narration"] = ["他没躲", "冰冷的触感让他睫毛微颤", "也将那抹暗红晕染开来"]   # 超过每段 2 句：按预算再删
    N.trim_narration(seg, "drama", closing=True)
    assert len(seg["lines"]) == 2 and "keep_narration" not in seg


def test_half_style_cuts_whole_sentences_shown_on_screen():
    seg = _alley()
    N.trim_narration(seg, "half", closing=True)
    texts = [ln["text"] for ln in seg["lines"]]
    assert 1 <= len(texts) < 3 and all(t.endswith("。") and "，" in t for t in texts)      # 整句为单位，不截半句
    assert sum(N.speech_seconds(t) for t in texts) <= seg["duration"] / 2


def test_apply_style_marks_scene_opening_and_closing():
    a, b = _alley(), _seg(["旁白：街上空无一人，只有更夫的梆子声。"], ["远景|街口|长街|固定|长街空荡|无|1"], scene="深夜长街")
    n = N.apply_style([a, b], "drama")
    assert n == 4 and [ln["text"] for ln in a["lines"]] == ["他没躲", "也将那抹暗红晕染开来。"]   # a 是这场戏的最后一段
    assert "分镜详情" in N.trim_note("drama", 2, n)
    c = _alley()
    c["keep_narration"] = ["他没躲"]
    assert N.apply_style([c], "full") == 0 and "keep_narration" not in c and len(c["lines"]) == 3


def test_build_segments_applies_project_style_and_keeps_default_for_direct_callers():
    """拆分镜落库：按作品的旁白风格删旁白，时长不缩；不传风格的旧调用方式不删。"""
    from api.shot import build_segments
    item = {"scene": "暴雨青石老巷，深夜", "pos": "沈砚在左，黑衣人在右", "mood": "肃杀", "sound": "密集雨声",
            "lines": ["旁白：刀锋贴着沈砚的耳畔划过，冰冷的触感让他睫毛微颤。", "旁白：他没躲，反手将短匕刺入了对方咽喉。",
                      "黑衣人：这就是你要找的？"],
            "beats": ["特写|沈砚左侧|侧脸与刀锋|固定|刀锋贴着沈砚耳畔划过，睫毛微颤|眼神不动|1",
                      "中近景|两人侧面|沈砚与黑衣人|固定|沈砚反手将短匕刺入黑衣人咽喉|咬肌绷紧|2",
                      "近景|正面|黑衣人头肩|固定|黑衣人捂着颈侧抬眼|瞪大双眼|3"]}
    names = {"沈砚", "黑衣人"}
    full, _ = build_segments([SS.expand_segment(dict(item), names)], MODEL, names, set())
    drama, notes = build_segments([SS.expand_segment(dict(item), names)], MODEL, names, set(), narration_style="drama")
    assert len(full[0]["lines"]) == 3 and "cut_lines" not in full[0]
    assert [(ln["speaker"], ln["text"]) for ln in drama[0]["lines"]] == [("旁白", "他没躲"), ("黑衣人", "这就是你要找的？")]
    assert drama[0]["duration"] == full[0]["duration"] and len(drama[0]["beats"]) == len(full[0]["beats"])
    assert len(drama[0]["cut_lines"]) == 2 and drama[0]["narration_style"] == "drama"
    assert drama[0]["text"] and "刀锋贴着" not in drama[0]["text"]                # 兼容旧字段也跟着变
    assert any("旁白风格“剧情动漫”" in n for n in notes)
