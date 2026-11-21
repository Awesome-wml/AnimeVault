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
    assert [b["action"] for b in bs] == ["铁面具抬手指向沈砚的左臂", "沈砚攥紧短匕", "沈砚挺直脊背"]
    assert [b["line_refs"] for b in bs] == [[1], [], [2]]          # 一句台词只在一个小镜头里登记
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
