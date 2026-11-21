"""真实拆分镜结果（《断雨残灯》54 段）里暴露的问题：字段错位、兜底动作穿帮、表情归错人、光影与时辰冲突。"""
from core import bystander as BY
from core import shot_split as SS
from core import video_prompt as VP


def test_extra_pipe_does_not_shift_fields():
    raw = ("中景|两人之间侧位，与胸齐平，平视|沈砚前倾起势与铁面具拔刀身影，背景巷弄||固定|铁面具肩线一沉，长刀出鞘半寸|"
           "面具后目光暴起|4|青光只亮在刀脊一线，不形成光罩|沈砚重心压低")
    b = SS.parse_beat(raw)
    assert b["move"] == "固定" and b["composition"].startswith("沈砚前倾")
    assert b["line_refs"] == [4] and "4" not in b["action"]
    assert b["boundary"].startswith("青光只亮") and b["others"] == "沈砚重心压低"


def test_expression_wu_and_refs_after_extra_pipe():
    raw = "特写|正对青石板，俯拍|石板缝隙与匕身||快速推近|短匕刺入石板缝隙|无|1，2||铁面具瞳孔骤缩"
    b = SS.parse_beat(raw)
    assert b["move"] == "快速推近" and b["expression"] == "" and b["line_refs"] == [1, 2]
    assert b["others"] == "铁面具瞳孔骤缩"


def test_others_written_in_boundary_slot_is_moved():
    b = SS.parse_beat("中近景|船头正前，平视|白衣男子合扇而立|固定|白衣男子点头|眼神转冷||沈砚立于巷中、雨水冲刷衣角")
    assert b["boundary"] == "" and b["others"] == "沈砚立于巷中、雨水冲刷衣角"
    real = SS.parse_beat("中景|侧面|刀身|固定|刀光一闪|无|1|金光只缠在扇刃边缘，不形成光球")
    assert real["boundary"].startswith("金光只缠")


def _fight_seg(**kw):
    seg = {"scene": "暴雨老城巷弄，深夜", "positions": "沈砚在左，铁面具在右", "mood": "惊险",
           "characters": ["沈砚", "铁面具"],
           "lines": [{"speaker": "旁白", "text": "刀光一闪。", "kind": "narration", "start": 0.5, "end": 2}],
           "beats": [{"shot_size": "中景", "action": "他撞破雨幕向前疾掠", "expression": "", "line_refs": [1]},
                     {"shot_size": "中景", "action": "沈砚侧身避开刀锋", "expression": "", "line_refs": []}]}
    seg.update(kw)
    return seg


def test_fight_scene_fallback_has_no_table_or_cup():
    for items in BY.plan_others(_fight_seg()):
        for _, text in items:
            assert not any(w in text for w in BY.SEATED_WORDS), text
            assert "语气" not in text


def test_standing_scene_without_action_mood_drops_seated_items():
    seg = _fight_seg(mood="沉静")
    for items in BY.plan_others(seg):
        for _, text in items:
            assert not any(w in text for w in BY.SEATED_WORDS), text


def test_focus_person_is_not_their_own_bystander():
    seg = _fight_seg(characters=["沈砚"], positions="沈砚在中央")
    assert BY.plan_others(seg) == [[], []]
    plan = BY.plan_others(_fight_seg())
    assert all(n != "沈砚" for n, _ in plan[0])     # “他撞破雨幕”：沈砚是焦点，旁观者只有铁面具


def test_expression_goes_to_speaker_not_object():
    lines = [{"speaker": "旁白", "text": "x", "kind": "narration"},
             {"speaker": "铁面具", "text": "沈探客。", "kind": "onscreen"}]
    beats = [{"action": "他抬刀指向沈砚方向", "expression": "下颌微抬，语气倨傲", "line_refs": [2]},
             {"action": "他一字一句开口", "expression": "眉骨压低", "line_refs": []}]
    people = ["铁面具", "沈砚"]
    assert VP._person_expression("铁面具", beats, people, lines) == "下颌微抬，语气倨傲"
    assert VP._person_expression("沈砚", beats, people, lines) == ""


def test_beat_rhythm_warnings_and_prompt_rules():
    from core import shot_timing as ST
    from core.prompt_registry import get_entry
    segs = [{"shot_no": 1, "beats": [{"start": 0, "end": 15}]},
            {"shot_no": 2, "beats": [{"start": 0, "end": 3}, {"start": 3, "end": 13}, {"start": 13, "end": 15}]},
            {"shot_no": 3, "beats": [{"start": 0, "end": 7}, {"start": 7, "end": 15}]}]
    w = ST.beat_rhythm_warnings(segs)
    assert len(w) == 2 and "段 1 的开场小镜头" in w[0] and "段 2 第 2 个小镜头有 10 秒" in w[1]
    for key in ("split_shots", "split_shots_script"):
        text = get_entry(key)["constraint"]
        assert "视觉钩子" in text and "两个小镜头写同一个台词序号" in text and "只调画面，不改不加台词" in text
    assert "本集最后一场停在悬念" in get_entry("script_convert")["constraint"]


# ---------- 第三轮：真实 54 段分镜（《断雨残灯》重拆）回放发现的问题 ----------

def test_trailing_pipe_does_not_scramble_beat():
    from core.shot_split import parse_beat
    b = parse_beat("特写|拳腹相触处，轻微仰拍|两截衣衫相接，背景虚化雨幕|固定|拳头砸进腹部，衣料凹陷|铁面具眼白一翻|5|"
                   "淡金气浪只在拳腹相触处炸开，一秒即散，不形成光球|沈砚小臂肌肉贲张|")
    assert b["move"] == "固定" and b["composition"].startswith("两截衣衫")
    assert b["action"] == "拳头砸进腹部，衣料凹陷" and b["line_refs"] == [5]
    assert b["boundary"].startswith("淡金气浪") and b["others"] == "沈砚小臂肌肉贲张"


def test_swapped_boundary_and_others_are_put_back():
    from core.shot_split import parse_beat
    b = parse_beat("中近景|铁面具正前方|铁面具头肩加长刀|固定|铁面具一振长刀|面具后低笑|2,3|封家黑衣人握刀肃立，雨水顺刀尖滴落|"
                   "青光只缠在刀身，持续两秒后淡去，不形成光球")
    assert b["boundary"].startswith("青光只缠在刀身") and b["others"].startswith("封家黑衣人")


def test_hollow_beat_is_dropped_and_boundary_kept():
    from core.shot_split import expand_segment
    seg = expand_segment({"lines": ["旁白：长刀擦着肩膀划过。"], "beats": [
        "近景|沈砚左肩侧|肩部衣料与刀锋残影|固定|刀锋掠过，衣角飘落|倒吸冷气|1",
        "特效边界段略||||||||刀光只在肩侧掠出一道残影，持续半秒即逝，不见伤口与血迹"]})
    assert len(seg["beats"]) == 1 and seg["beats"][0]["boundary"].startswith("刀光只在肩侧")


def _timed(lines, beats, duration=15):
    from core.shot_timing import normalize_beats, normalize_lines, time_lines
    ls = normalize_lines(lines)
    time_lines(ls, duration)
    return ls, normalize_beats(beats, duration, len(ls), lines=ls)


def test_two_beats_on_one_line_both_survive():
    """两个小镜头写同一句台词：原来前一个零长度被丢掉（说话人的镜头没了），现在对半分。"""
    ls, bs = _timed([{"speaker": "铁面具", "text": "你那只手，真的还能动吗？", "kind": "onscreen"},
                     {"speaker": "旁白", "text": "沈砚站在阵法中央，雨水打湿了他的头发，脊背依然挺得笔直。", "kind": "narration"}],
                    [{"shot_size": "中近景", "action": "铁面具抬手指向沈砚的左臂", "line_refs": [1]},
                     {"shot_size": "特写", "action": "沈砚攥紧短匕", "line_refs": [1]},
                     {"shot_size": "中景", "action": "沈砚挺直脊背", "line_refs": [2]}])
    # 最后一镜有 9 秒多，超过 8 秒，代码自动拆成两个景别（见 test_long_beat_is_split_*）
    assert [b["action"] for b in bs] == ["铁面具抬手指向沈砚的左臂", "沈砚攥紧短匕", "沈砚挺直脊背", "延续上一镜：沈砚挺直脊背"]
    assert [b["line_refs"] for b in bs][:3] == [[1], [], [2]]      # 一句台词只在一个小镜头里登记
    assert bs[0]["end"] - bs[0]["start"] >= 0.8 and bs[1]["end"] - bs[1]["start"] >= 0.8


def test_slack_is_spread_between_lines_not_left_at_tail():
    ls, bs = _timed([{"speaker": "沈砚", "text": "找到了。", "kind": "onscreen"},
                     {"speaker": "旁白", "text": "沈砚低声自语，声音沙哑，透着被雨水泡透的寒意。", "kind": "narration"},
                     {"speaker": "旁白", "text": "他停下脚步，左肩旧伤传来钻心刺痛，让他呼吸微微一滞。", "kind": "narration"}],
                    [{"shot_size": "近景", "action": "沈砚停步扶墙", "line_refs": [1, 2]},
                     {"shot_size": "特写", "action": "他抬手按住左肩", "line_refs": [3]}])
    assert ls[1]["start"] - ls[0]["end"] > 1.0 and ls[-1]["end"] <= 14.7
    assert bs[-1]["end"] - bs[-1]["start"] <= 8.0                  # 原来是 9.5 秒，尾巴上哑 4.7 秒


def test_action_beat_without_line_starts_after_speech():
    ls, bs = _timed([{"speaker": "白衣男子", "text": "好，很好。", "kind": "onscreen"}],
                    [{"shot_size": "近景", "action": "他微微颔首", "line_refs": [1]},
                     {"shot_size": "中景", "action": "沈砚拔出长刀", "line_refs": []}])
    assert bs[1]["start"] >= ls[0]["end"]


def test_expression_follows_camera_subject_not_shared():
    from core.video_prompt import character_detail
    shot = {"characters": ["封家黑衣人", "沈砚"], "mood": "紧张",
            "lines": [{"speaker": "旁白", "text": "刀锋贴着沈砚的耳畔划过。", "kind": "narration"}],
            "beats": [{"shot_size": "特写", "camera": "正对沈砚侧脸，与眼齐平", "action": "睫毛轻颤，水珠从鼻尖滑落",
                       "expression": "睫毛微颤，呼吸一滞", "line_refs": [1], "others": "封家黑衣人持刀逼近"}]}
    detail = character_detail(shot)
    assert "沈砚：表情随情绪走：睫毛微颤" in detail and "封家黑衣人：表情随情绪走" not in detail
    assert "随对方语气" not in detail                               # 纯旁白的动作戏不写倾听小动作


def test_downed_and_acting_people_get_fitting_fallbacks():
    from core.bystander import beat_phrases
    shot = {"characters": ["沈砚", "铁面具"], "mood": "疲惫", "scene": "暴雨青石老巷",
            "positions": "沈砚独占画面中右侧，面朝左侧倒地铁面具", "lines": [],
            "beats": [{"shot_size": "近景", "camera": "沈砚右侧", "action": "沈砚垂眼望着倒地铁面具，肩线垮下",
                       "composition": "沈砚头肩加地上铁面具", "line_refs": []}]}
    assert "铁面具倒在原地不动" in beat_phrases(shot)[0]
    shot2 = {"characters": ["铁面具", "沈砚"], "mood": "雷霆一击", "scene": "暴雨青石老巷", "positions": "", "lines": [],
             "beats": [{"shot_size": "中近景", "camera": "沈砚上方，俯拍", "action": "脚尖踩上匕柄旁石面，猛力下蹬",
                        "composition": "全身下压加青石板", "line_refs": []},
                       {"shot_size": "中景", "camera": "巷道侧面", "action": "铁面具背撞断墙滑坐在地", "line_refs": []}]}
    p = beat_phrases(shot2)
    assert p[0].startswith("其余在场者：铁面具")                     # 出招的沈砚是焦点，不是旁观者
    assert "桌" not in "".join(p) and "衣袖" not in "".join(p)


# ---------- 第四轮：新规则重拆后的 53 段回放 ----------

def test_action_split_by_extra_pipe_is_rejoined():
    from core.shot_split import parse_beat
    b = parse_beat("中景|沈砚侧前方，与肩同高，平视|沈砚与袭来的刀气光痕，背景光壁|快速横移|沈砚身体前倾蓄力，脚尖碾住石板边缘|没有躲闪|"
                   "眼神决绝，肩膀下沉|3|刀气只呈一道淡白光痕擦过，持续一秒即散，不炸开烟尘|阵沿黑衣人齐齐举刀屏息")
    assert b["move"] == "快速横移" and b["composition"].startswith("沈砚与袭来的刀气")
    assert b["action"] == "沈砚身体前倾蓄力，脚尖碾住石板边缘，没有躲闪" and b["expression"] == "眼神决绝，肩膀下沉"
    assert b["line_refs"] == [3] and b["boundary"].startswith("刀气只呈") and b["others"].startswith("阵沿黑衣人")


def test_narration_same_as_action_is_not_replaced():
    from core.video_prompt import dedupe_dialogue
    pic = "[12.1-15秒]特写，正对沈砚双眼，急推，沈砚瞳孔骤缩，睫毛上雨珠滑落"
    lines = [{"speaker": "旁白", "text": "沈砚瞳孔骤缩。", "kind": "narration"}]
    assert dedupe_dialogue(pic, lines, [{"action": "沈砚瞳孔骤缩，睫毛上雨珠滑落"}]) == pic


def test_repeated_lines_across_segments_are_dropped():
    from core.shot_timing import drop_repeated_lines
    n = {"speaker": "旁白", "kind": "narration"}
    t = {"speaker": "铁面具", "kind": "onscreen"}
    items = [
        {"lines": [dict(n, text="那是一块残缺的玉牌。"), dict(t, text="封家大少爷问你好，当年那一剑，你后悔吗？")], "beats": []},
        {"lines": [dict(t, text="封家大少爷问你好，当年那一剑，你后悔吗？"), dict(n, text="沈砚抬起头。"), dict(n, text="他缓缓握紧短匕。")],
         "beats": [{"line_refs": [2]}, {"line_refs": [3]}]},
        {"lines": [dict(n, text="夜色渐深。"), dict(n, text="沈砚的身影在雨中越走越远，")], "beats": [{"line_refs": [1, 2]}]},
        {"lines": [dict(n, text="沈砚的身影在雨中越走越远，像是一个孤独的行者。")], "beats": [{"line_refs": [1]}]},
    ]
    notes = drop_repeated_lines(items)
    assert len(notes) == 2
    assert [ln["text"] for ln in items[1]["lines"]] == ["沈砚抬起头。", "他缓缓握紧短匕。"]
    assert [b["line_refs"] for b in items[1]["beats"]] == [[1], [2]]
    assert [ln["text"] for ln in items[2]["lines"]] == ["夜色渐深。"] and items[2]["beats"][0]["line_refs"] == [1]
    assert len(items[3]["lines"]) == 1


def test_speech_overflow_warning():
    from core.shot_timing import speech_overflow_warnings
    seg = {"shot_no": 17, "duration": 15, "lines": [{"text": "字" * 79, "speaker": "旁白", "kind": "narration"}]}
    assert "段 17" in speech_overflow_warnings([seg])[0]
    assert speech_overflow_warnings([dict(seg, lines=[{"text": "字" * 50}])]) == []


def test_standing_scene_fallback_and_style_tone():
    from core.bystander import beat_phrases
    from core.video_prompt import SCENE_TONE_HINT, character_detail, fit_style_to_scene
    shot = {"characters": ["铁面具", "沈砚"], "mood": "压抑", "scene": "暴雨青石老巷废墟，深夜", "positions": "",
            "lines": [{"speaker": "铁面具", "text": "结阵！", "kind": "onscreen"}],
            "beats": [{"shot_size": "中景", "camera": "铁面具右前方", "action": "铁面具站定，十指翻飞", "line_refs": [1]}]}
    p = beat_phrases(shot)[0]
    assert "沈砚" in p and "衣袖" not in p and "戒指" not in p
    s = fit_style_to_scene("3D 国漫风格，电影级光影，空灵缥缈的青白色调，云雾意境，柔和仙光", "暴雨青石老巷，深夜")
    assert "仙光" not in s and "云雾" not in s and "3D 国漫风格" in s and s.endswith(SCENE_TONE_HINT)
    assert fit_style_to_scene("3D 国漫风格，柔和仙光", "云海仙山，清晨") == "3D 国漫风格，柔和仙光"
    solo = {"characters": ["沈砚"], "mood": "隐忍", "lines": [], "beats": [{"action": "沈砚摸出药丸，仰头吞下"}]}
    assert "对手" not in character_detail(solo)


# ---------- 第五轮：成片回看（第 1 段 10 秒开场镜头被模型自己补切）+ 52 段打分里的穿帮 ----------
def test_long_beat_is_split_at_line_start_and_is_idempotent():
    """一个小镜头挂两句旁白共 10 秒：模型撑不住会自己切一个站着不动的镜头。代码在第二句开口前拆开、换景别。"""
    from core.shot_timing import MAX_BEAT_SECONDS, beat_rhythm_warnings, normalize_beats
    lines = [{"speaker": "旁白", "text": "暴雨如注，冲刷着青石板缝隙里积攒了百年的苔藓。", "kind": "narration"},
             {"speaker": "旁白", "text": "巷弄里弥漫着挥之不去的痕迹，一抹暗红怎么也洗不净。", "kind": "narration"},
             {"speaker": "旁白", "text": "刀锋贴着沈砚的耳畔划过，冰冷的触感让他睫毛微颤。", "kind": "narration"}]
    ls, bs = _timed(lines, [{"shot_size": "特写", "camera": "贴近地面", "action": "雨水冲刷苔藓", "line_refs": [1]},
                            {"shot_size": "特写", "camera": "沈砚左侧", "action": "刀锋贴耳掠过", "line_refs": [3]}])
    assert all(b["end"] - b["start"] <= MAX_BEAT_SECONDS for b in bs)
    assert len(bs) == 3 and bs[1].get("auto_split") and bs[1]["shot_size"] == "近景"
    assert bs[1]["action"] == "延续上一镜：雨水冲刷苔藓"
    assert abs(bs[1]["start"] - (ls[1]["start"] - 0.2)) < 0.11      # 切在第二句开口前
    again = normalize_beats(bs, 15, len(ls), lines=ls)              # 手工改台词后重新规整：不会越拆越多
    assert [(b["start"], b["end"], b["action"]) for b in again] == [(b["start"], b["end"], b["action"]) for b in bs]
    notes = beat_rhythm_warnings([{"shot_no": 2, "beats": bs}])
    assert any("已自动拆成两个景别" in n for n in notes) and not any("画面会拖" in n for n in notes)


def test_long_single_line_beat_is_split_in_the_middle():
    ls, bs = _timed([{"speaker": "旁白", "text": "但他的呼吸开始变得急促，左肩的旧伤传来阵阵撕裂般的疼痛，每一次挥刀都在牵扯着那里的神经。", "kind": "narration"},
                     {"speaker": "旁白", "text": "他不是不知道疼。", "kind": "narration"}],
                    [{"shot_size": "特写", "action": "左肩随呼吸微颤", "line_refs": [1]},
                     {"shot_size": "中近景", "action": "沈砚甩了甩左手", "line_refs": [2]}])
    assert len(bs) == 3 and bs[1].get("auto_split") and bs[1]["line_refs"] == []
    assert all(b["end"] - b["start"] <= 8.0 for b in bs)


def test_onscreen_line_is_not_cut_away_mid_sentence():
    """白衣男子一句 6 秒多的台词还没说完，画面不能切到沈砚的反应镜头（清单写“第 2 镜发声”）。"""
    ls, bs = _timed([{"speaker": "沈砚", "text": "封无极派你来，就是为了对付我？", "kind": "onscreen"},
                     {"speaker": "白衣男子", "text": "对付你？封家大少爷说，只要你能活着走出这片巷子，他就给你一个解释的机会。", "kind": "onscreen"}],
                    [{"shot_size": "特写", "action": "沈砚仰头逼问", "line_refs": [1]},
                     {"shot_size": "近景", "action": "白衣男子低笑出声", "line_refs": [2]},
                     {"shot_size": "中近景", "action": "沈砚攥着令牌的指节发白", "line_refs": []}])
    reaction = [b for b in bs if b["action"] == "沈砚攥着令牌的指节发白"]
    assert all(b["start"] >= ls[1]["end"] for b in reaction)       # 反应镜头要么排在说完之后，要么并掉
    speaking = [b for b in bs if "白衣男子低笑出声" in b["action"]]
    assert speaking[0]["start"] <= ls[1]["start"] and speaking[-1]["end"] >= ls[1]["end"] - 0.11


def test_empty_shot_offscreen_voice_and_hit_target_get_no_bystander_filler():
    from core.bystander import beat_phrases, shot_people
    from core.video_prompt import character_detail, overall_setting
    # 空镜里不配人
    shot = {"characters": ["沈砚", "白衣男子"], "mood": "寂寥收场", "scene": "暴雨青石老巷", "lines": [],
            "beats": [{"shot_size": "空镜", "camera": "低机位贴近水面", "action": "水面涟漪一圈圈散开", "line_refs": []}]}
    assert beat_phrases(shot) == [""]
    # 只有画外音的人不算画面人物
    shot = {"characters": ["白衣男子", "沈砚"], "mood": "惊疑骤起", "scene": "暴雨青石老巷，深夜",
            "lines": [{"speaker": "白衣男子", "text": "这就是你要找的？", "kind": "offscreen"}],
            "beats": [{"shot_size": "中近景", "action": "沈砚猛地抬头望向巷道高处", "line_refs": [1]}]}
    assert shot_people(shot) == ["沈砚"]
    assert "白衣男子" not in overall_setting(shot) and "白衣男子：" not in character_detail(shot)
    # 正在挨打的人不另配“握紧兵器盯着对方”
    shot = {"characters": ["沈砚", "铁面具"], "mood": "爆烈沉重", "scene": "暴雨青石老巷", "lines": [],
            "beats": [{"shot_size": "中景", "action": "沈砚右拳结结实实砸在铁面具腹部", "line_refs": []}]}
    assert beat_phrases(shot) == [""]


def test_person_knocked_out_before_this_segment_is_down_from_first_beat():
    from core.bystander import beat_phrases
    shot = {"characters": ["沈砚", "铁面具"], "mood": "惊疑骤起", "scene": "暴雨青石老巷", "positions": "沈砚蹲在断墙前", "lines": [],
            "beats": [{"shot_size": "中景", "action": "沈砚从暗袋里掏出卷轴和一枚令牌", "line_refs": []},
                      {"shot_size": "中近景", "action": "沈砚猛地抬头", "others": "铁面具瘫在原地，肩头微微起伏", "line_refs": []}]}
    assert "铁面具倒在原地不动" in beat_phrases(shot)[0]
    # 这一段里才被打飞的：倒下之前的小镜头不算倒地
    shot = {"characters": ["沈砚", "铁面具"], "mood": "对峙", "scene": "暴雨青石老巷", "positions": "", "lines": [],
            "beats": [{"shot_size": "中景", "action": "沈砚缓缓抬手", "line_refs": []},
                      {"shot_size": "中景", "action": "铁面具背撞断墙滑坐在地，瘫倒不动", "line_refs": []}]}
    assert "倒在原地不动" not in beat_phrases(shot)[0]


def test_expression_of_unlisted_crowd_or_other_hand_is_not_given_to_lead():
    from core.video_prompt import character_detail
    shot = {"characters": ["沈砚"], "mood": "冷酷", "scene": "暴雨青石老巷", "lines": [],
            "beats": [{"shot_size": "中近景", "camera": "沈砚左后方", "action": "沈砚侧身让过刀锋", "expression": "眼神紧盯前方", "line_refs": []},
                      {"shot_size": "中景", "camera": "巷道正面", "action": "两名黑衣人闷声倒下，捂着脖子蜷缩", "expression": "痛苦地蜷起肩膀",
                       "composition": "沈砚凌空背影，两名黑衣人在右侧先后倒地", "line_refs": []}]}
    d = character_detail(shot)
    assert "眼神紧盯前方" in d and "痛苦地蜷起肩膀" not in d
    shot = {"characters": ["铁面具", "沈砚"], "mood": "破招", "scene": "暴雨青石老巷", "lines": [],
            "beats": [{"shot_size": "近景", "camera": "手腕侧面", "action": "指尖点落，对方手指逐根松脱", "expression": "眼神冷定，出指不停",
                       "composition": "手腕被连点处特写，铁面具手指僵直", "line_refs": []}]}
    assert "铁面具：表情随情绪走：眼神冷定" not in character_detail(shot)


def test_tense_standoff_listener_does_not_nod_and_downed_has_no_relaxed_look():
    from core.video_prompt import character_detail
    shot = {"characters": ["铁面具", "沈砚"], "mood": "困局", "scene": "暴雨青石老巷，深夜",
            "lines": [{"speaker": "铁面具", "text": "困兽之斗，没什么意思。", "kind": "onscreen"}],
            "beats": [{"shot_size": "中近景", "action": "铁面具俯视阵中", "expression": "嘴角一撇", "line_refs": [1]}]}
    d = character_detail(shot)
    assert "点头" not in d and "沈砚：" in d
    shot = {"characters": ["沈砚", "铁面具"], "mood": "疲惫警觉", "scene": "暴雨青石老巷", "positions": "铁面具瘫在墙根", "lines": [],
            "beats": [{"shot_size": "近景", "action": "沈砚抹了把脸上的雨水", "line_refs": []}]}
    assert "铁面具：不说话，倒在原地不动" in character_detail(shot)
