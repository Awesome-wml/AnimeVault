"""T-273 非说话人物不能像木头：每个小镜头给在场者各自的持续微动作（其余在场者）。不连任何模型。"""
import re

from core import bystander as BY
from core import prompt_tpl as T
from core import shot_split as SS
from core import shot_timing as ST
from core import video_prompt as VP
from core.prompt_registry import get_entry

NAMES = ("陆川", "陈子昂", "赵一帆")


def _beats(with_others=False):
    bs = [
        {"shot_size": "中景", "camera": "沙发正前方，平视", "composition": "三人坐沙发，赵一帆背对镜头在前景", "move": "固定",
         "action": "陆川放下酒杯，抬眼看向陈子昂", "expression": "嘴角压着笑", "boundary": "", "line_refs": [1], "start": 0, "end": 5},
        {"shot_size": "中近景", "camera": "陆川右前方，平视", "composition": "陆川头肩加陈子昂侧脸", "move": "缓慢推近",
         "action": "陆川指腹转着杯壁", "expression": "眼神发冷", "boundary": "", "line_refs": [2], "start": 5, "end": 10},
        {"shot_size": "远景", "camera": "包厢门口俯拍", "composition": "整个包厢", "move": "固定",
         "action": "陈子昂端杯起身", "expression": "喉结滚动", "boundary": "", "line_refs": [], "start": 10, "end": 15},
    ]
    if with_others:
        bs[0]["others"] = "陈子昂靠沙发背抿酒、视线跟着陆川；赵一帆背对镜头低头划手机、拇指偶尔滑动"
    return bs


def _seg(beats=None, **kw):
    seg = {"shot_no": 14, "duration": 15, "scene": "云顶包厢，深夜", "positions": "陆川在左，陈子昂在中，赵一帆在右背对镜头",
           "mood": "紧张", "characters": list(NAMES), "continuity": "开场", "sound": "杯碰桌",
           "lines": [{"speaker": "陆川", "text": "这杯酒我敬你，但话要说清楚。", "kind": "onscreen", "start": 0.5, "end": 4},
                     {"speaker": "陆川", "text": "三年前的事，你还记得多少？", "kind": "onscreen", "start": 5.5, "end": 9}],
           "beats": beats or _beats(), "tail": "陈子昂起身"}
    seg.update(kw)
    seg["video_prompt"] = kw.get("video_prompt") or ST.compose_video_prompt(seg)
    return seg


def _chunks(picture):
    marks = list(re.finditer(r"\[\d+(?:\.\d+)?-\d+(?:\.\d+)?秒\]", picture))
    return [picture[m.end(): marks[i + 1].start() if i + 1 < len(marks) else len(picture)] for i, m in enumerate(marks)]


def _others_of(chunk, name):
    """“其余在场者：…”里某人的那一句动作（到下一个分号）；没有返回空串。"""
    if BY.LABEL not in chunk:
        return ""
    body = chunk.split(BY.LABEL, 1)[1].split("；此时")[0]
    for part in body.split("；"):
        if part.startswith(name):
            return part
    return ""


def test_contract_and_templates_require_everyone_to_move():
    must = ("本小镜头画面里出现的每一个人物都必须有动作", "焦点人物写 action", "其余在场者", "不得留空",
            "视线跟随", "重心微调", "手部小动作", "偶尔眨眼", "不同人物动作不同", "不用同一套话", "背对镜头")
    for key, tpl in (("split_shots", T.SHOT_SPLIT_PROMPT), ("split_shots_script", T.SHOT_SPLIT_SCRIPT_PROMPT)):
        e = get_entry(key)
        for text in (tpl, e["constraint"]):
            for w in must:
                assert w in text, (key, w)
            assert "第 9 段" in text
        # 契约里也写明第 9 段并给出示例
        assert "其余在场者" in e["contract"] or "||" in e["contract"]


def test_parse_beat_ninth_field_and_back_compat():
    b = SS.parse_beat("中景|平视|三人入画|固定|陆川抬眼|嘴角一撇|1||陈子昂抿酒；赵一帆划手机")
    assert b["others"] == "陈子昂抿酒；赵一帆划手机" and b["boundary"] == "" and b["line_refs"] == [1]
    b8 = SS.parse_beat("特写|a|b|固定|金光泛起|无|1|金光只在掌心|赵一帆低头")
    assert b8["boundary"] == "金光只在掌心" and b8["others"] == "赵一帆低头"
    old = SS.parse_beat("中景|平视|三人入画|固定|陆川抬眼|嘴角一撇|1")
    assert "others" not in old   # 老数据不带这个键
    b["others"] = "陈子昂抿酒；赵一帆划手机"
    out = ST.normalize_beats([old, b], 10, 1)
    assert out[1]["others"].startswith("陈子昂") if len(out) > 1 else True
    assert "others" not in out[0]


def test_old_beats_without_others_do_not_break():
    seg = _seg()
    ST.normalize_beats(seg["beats"], 15, 2)
    assert VP.assemble_video_prompt(seg, [])


def test_every_beat_describes_every_non_focus_person_old_data_fallback():
    seg = _seg()
    chunks = _chunks(_picture(VP.assemble_video_prompt(seg, [])))
    assert len(chunks) == 3
    # 小镜头 1/2 焦点是陆川：陈子昂、赵一帆都有动作；小镜头 3 焦点是陈子昂：陆川、赵一帆有动作
    expect = [("陈子昂", "赵一帆"), ("陈子昂", "赵一帆"), ("陆川", "赵一帆")]
    for chunk, who in zip(chunks, expect):
        assert BY.LABEL in chunk and "不静止定格" in chunk
        acts = [_others_of(chunk, n) for n in who]
        assert all(len(a) > len(n) + 4 for a, n in zip(acts, who)), chunk
        assert acts[0] != acts[1]            # 同镜头不同人动作不同


def test_fallback_same_person_not_repeated_in_adjacent_beats():
    plan = BY.plan_others(_seg())
    for n in NAMES:
        seq = [dict(items).get(n) for items in plan if dict(items).get(n)]
        assert all(a != b for a, b in zip(seq, seq[1:])), (n, seq)
    for items in plan:
        texts = [t for _, t in items]
        assert len(set(texts)) == len(texts)


def test_back_facing_person_keeps_moving():
    plan = BY.plan_others(_seg())
    for items in plan:
        back = dict(items)["赵一帆"]
        assert back.startswith("背对镜头") and ("呼吸" in back or "肩" in back or "转头" in back)
    assert "动作幅度稍大" in dict(plan[2])["赵一帆"]     # 远景里幅度写大


def test_library_has_enough_variety():
    assert len(BY.REACTIONS) >= 8 and len(set(BY.REACTIONS)) == len(BY.REACTIONS)
    assert len(BY.BACK_ACTIONS) >= 3


def test_fallback_library_has_no_modern_items():
    """兜底动作库不知道本剧时代，不得含手机/手表等现代物件（风控问题记录 §2.3：仙侠廊道里“低头看手机”穿帮）。"""
    for text in BY.REACTIONS + BY.BACK_ACTIONS:
        assert not any(w in text for w in BY.MODERN_ITEMS), text
    # 兜底出来的“其余在场者”整句也不含现代物件（模型自己写在 beats 里的沙发、手机不归这里管）
    for phrase in BY.beat_phrases(_seg(scene="青云宗廊道，黄昏")):
        assert not any(w in phrase for w in BY.MODERN_ITEMS), phrase


def test_explicit_others_used_verbatim_and_not_duplicated():
    seg = _seg(_beats(True))
    pic = seg["video_prompt"]
    assert "陈子昂靠沙发背抿酒、视线跟着陆川；赵一帆背对镜头低头划手机、拇指偶尔滑动" in pic
    assert pic.count(BY.LABEL) == 3          # 第 1 镜是模型写的，另外两镜兜底；注入时不重复
    p = _picture(VP.assemble_video_prompt(seg, []))
    assert p.count(BY.LABEL) == 3
    # 其余在场者紧跟在焦点动作之后、台词标注之前
    first = _chunks(p)[0]
    assert first.index("陆川放下酒杯") < first.index(BY.LABEL) < first.index("此时陆川说出台词①")


def test_old_stored_picture_gets_others_injected():
    """老数据：video_prompt 是旧版生成的（没有其余在场者），组装时兜底补上。"""
    seg = _seg()
    seg["video_prompt"] = seg["video_prompt"].replace(BY.LABEL, "@@")
    seg["video_prompt"] = re.sub(r"；@@.*?不静止定格", "", seg["video_prompt"])
    assert BY.LABEL not in seg["video_prompt"]
    pic = _picture(VP.assemble_video_prompt(seg, []))
    assert pic.count(BY.LABEL) == 3


def test_character_detail_is_per_person_without_repeated_boilerplate():
    d = VP.character_detail(_seg())
    for n in NAMES:
        assert f"{n}：" in d
    assert d.count("嘴唇自然闭合不张嘴") == 2
    silent = [d.split(f"{n}：")[1].split("；")[0] for n in ("陈子昂", "赵一帆")]
    assert silent[0] != silent[1]
    assert d.count("自然眨眼") == 1


def test_others_survive_budget_trim(monkeypatch):
    seg = _seg()
    monkeypatch.setattr(VP, "MAX_PROMPT_CHARS", 10 ** 6)
    full = len(VP.assemble_video_prompt(seg, []))
    for limit in (full - 200, full - 600, 900):
        monkeypatch.setattr(VP, "MAX_PROMPT_CHARS", limit)
        p, w = VP.assemble_video_prompt_ex(seg, [])
        assert VP.TRIMMED_WARNING in w
        assert _picture(p).count(BY.LABEL) == 3 and "自然眨眼" in p
        assert "赵一帆背对镜头" in p


def test_close_up_and_empty_shot_have_no_bystanders():
    bs = [dict(_beats()[0], shot_size="特写", action="陆川的手指转着杯壁", composition="手和杯子"),
          dict(_beats()[1], shot_size="全景", action="包厢空镜，酒瓶反着光", expression="无", composition="空镜")]
    plan = BY.plan_others(_seg(bs))
    assert plan[0] == [] and plan[1] == []


def _picture(p):
    return re.search(r"【画面】(.*)", p).group(1)
