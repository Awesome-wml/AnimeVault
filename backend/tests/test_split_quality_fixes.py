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
