"""T-227 视频提示词导演级升级：7 段 beats、台词唯一清单、机位构图、镜头承接首帧、特效边界、多场景背景参考、总长预算。"""
import json
import re

from core import prompt_tpl as T
from core import shot_split as SS
from core import shot_timing as ST
from core import video_prompt as VP
from core.prompt_registry import get_entry
from core.video_models import get_video_model

FAST = get_video_model()
A_LINE = "你也配站在这里，我今天就要把话说清楚？"
B_LINE = "三个月后的族比，我等你。"


def _beats():
    return [
        {"shot_size": "中近景", "camera": "林风右后方，与肩同高，平视", "composition": "赵虎头肩加林风肩膀，背景朝向廊柱",
         "move": "固定", "action": "赵虎俯身逼近，俯视林风", "expression": "冷笑", "boundary": "", "line_refs": [1],
         "start": 0.0, "end": 4.0},
        {"shot_size": "特写", "camera": "左手正前方，与手背齐平，平视", "composition": "左手和古戒，背景是模糊雨幕",
         "move": "缓慢推近", "action": "林风握紧扫帚，左手青铜古戒泛起暗红微光", "expression": "指节攥白",
         "boundary": "微光只亮在古戒上，持续两秒后收敛，不扩散到手臂和脸、不形成光球", "line_refs": [2],
         "start": 4.0, "end": 9.0},
        {"shot_size": "近景", "camera": "林风正前方，与胸口齐平，平视", "composition": "头肩，背景是雨幕",
         "move": "固定", "action": "林风抬眼看向赵虎，转身走进雨里", "expression": "眼神笃定", "boundary": "", "line_refs": [],
         "start": 9.0, "end": 15.0},
    ]


def _seg(**kw):
    seg = {
        "shot_no": 2, "duration": 15, "scene": "暴雨演武场，黄昏", "positions": "赵虎在左，林风在右", "mood": "紧张",
        "characters": ["赵虎", "林风"], "continuity": "承接上一段：两人相对而立", "sound": "雨声",
        "lines": [
            {"speaker": "赵虎", "text": A_LINE, "kind": "onscreen", "start": 0.5, "end": 4.0},
            {"speaker": "旁白", "text": B_LINE, "kind": "narration", "start": 4.5, "end": 8.0},
        ],
        "beats": _beats(), "tail": "林风走进雨里",
    }
    seg.update(kw)
    seg["video_prompt"] = kw.get("video_prompt") or ST.compose_video_prompt(seg)
    return seg


def _scene_ref(i, name, **kw):
    return {"type": "场景", "name": name, "path": f"/s/{i}.png", **kw}


def _picture(p):
    return re.search(r"【画面】(.*)", p).group(1)


# ---------- A. 7 段 beats ----------
def test_beat_seven_fields_and_back_compat():
    b = SS.parse_beat("中近景|林风右后方，与肩同高，平视|赵虎头肩加林风肩膀，背景朝向廊柱|固定|赵虎俯身逼近|冷笑|1")
    assert (b["camera"], b["composition"], b["move"], b["action"], b["expression"], b["line_refs"], b["boundary"]) == \
        ("林风右后方，与肩同高，平视", "赵虎头肩加林风肩膀，背景朝向廊柱", "固定", "赵虎俯身逼近", "冷笑", [1], "")
    old6 = SS.parse_beat("中近景|过肩|固定|赵虎俯身逼近|冷笑|1")
    assert old6["composition"] == "" and old6["move"] == "固定" and old6["expression"] == "冷笑" and old6["line_refs"] == [1]
    old5 = SS.parse_beat("中近景|过肩|固定|赵虎俯身逼近|1")
    assert old5["composition"] == "" and old5["expression"] == "" and old5["action"] == "赵虎俯身逼近"
    # 构图和边界一路穿过 normalize_beats 落库
    out = ST.normalize_beats([SS.parse_beat("特写|a|b|固定|金光泛起|无|1|金光只在掌心")], 10, 1)
    assert out[0]["composition"] == "b" and out[0]["boundary"] == "金光只在掌心"


def test_templates_ask_for_seven_fields_in_both_places():
    """模板（prompt_tpl）与注册表（system.json / constraints.json）同步：7 段、机位位置高度、构图、边界。"""
    for key, tpl in (("split_shots", T.SHOT_SPLIT_PROMPT), ("split_shots_script", T.SHOT_SPLIT_SCRIPT_PROMPT)):
        e = get_entry(key)
        for text in (tpl, e["constraint"]):
            assert "景别|机位|构图|运镜|动作|表情|台词序号" in text and "7 段" in text
            assert "相对人物的位置与高度" in text and "背景朝向" in text and "边界" in text
        # 契约示例里的 beats 是 7 段（特效镜头 8 段）
        example = json.loads(e["contract"].split("结构如下（甲、乙只示意格式，实际内容按")[1].split("）：\n", 1)[1].replace("\n", ""))
        for seg in example["segments"]:
            for raw in seg["beats"]:
                assert len(raw.split("|")) in (7, 8), raw


# ---------- B. 台词唯一清单 ----------
def test_dialogue_only_in_list_once_and_not_in_picture():
    seg = _seg()
    p = VP.assemble_video_prompt(seg, [])
    heads = [ln.split("】")[0] + "】" for ln in p.split("\n")]
    assert heads == ["【整体设定】", "【硬性参数】", "【参考素材】", "【台词清单】", "【画面】", "【硬性禁区】"]
    assert p.count(A_LINE) == 1 and p.count(B_LINE) == 1
    assert A_LINE not in _picture(p) and B_LINE not in _picture(p)
    lst = p.split("【台词清单】")[1].split("\n")[0]
    assert lst.startswith("①[0.5-4秒·第1镜]赵虎") and A_LINE in lst and "②[4.5-8秒·第2镜]旁白：" + B_LINE in lst
    assert "以上为唯一发声依据" in lst and "不代表再次说出" in lst
    assert "每句只说一次，禁止回放、回声、双重人声" in lst
    assert "其他镜头和其他人物不发声" in lst and "自然闭嘴" in lst and "嘟囔、笑声" in lst
    # 画面里只写“此时说出台词①”；旁白是画外音、画面人物不张嘴
    pic = _picture(p)
    assert "此时赵虎说出台词①" in pic and "此时响起旁白（台词②）" in pic and "画面人物不张嘴" in pic
    # 说话人不在画面时的画外音 / 心声同样只出序号
    seg2 = _seg(lines=[{"speaker": "苏婉", "text": "住手，别再打了！", "kind": "offscreen", "start": 1, "end": 3},
                       {"speaker": "林风", "text": "再忍一忍吧。", "kind": "inner", "start": 4, "end": 6}],
                beats=[dict(_beats()[0], line_refs=[1]), dict(_beats()[1], line_refs=[2])])
    p2 = VP.assemble_video_prompt(seg2, [])
    assert p2.count("住手，别再打了") == 1 and p2.count("再忍一忍吧") == 1
    assert "苏婉不在画面里" in p2 and "此时画外响起苏婉的声音（台词①）" in _picture(p2)
    assert "林风心声" in p2 and "此时响起林风心声（台词②）" in _picture(p2)
    # 没有台词
    assert "本段无台词，画面中人物不开口说话" in VP.assemble_video_prompt(_seg(lines=[], beats=[]), [])


def test_old_picture_with_dialogue_text_is_deduped_on_assemble():
    """旧数据 / 手写画面里残留的“某某说：台词原文”在组装时换成序号，原文只剩清单里一份。"""
    seg = _seg(video_prompt=f"[0-4秒]中近景，赵虎俯身逼近；赵虎冷笑说：{A_LINE}；[4-8秒]特写，旁白念到{B_LINE}")
    p = VP.assemble_video_prompt(seg, [])
    assert p.count(A_LINE) == 1 and p.count(B_LINE) == 1
    assert "说出台词①" in _picture(p) and "台词②" in _picture(p)


# ---------- C. 镜头承接首帧 ----------
def test_continuity_sentence_from_previous_beat_tail():
    pic = ST.compose_video_prompt(_seg())
    spans = re.split(r"(?=\[\d+(?:\.\d+)?-\d+(?:\.\d+)?秒\])", pic)
    spans = [s for s in spans if s.startswith("[")]
    assert len(spans) == 3
    assert "承接上一镜结尾" not in spans[0]  # 第 1 个小镜头接的是上一段（段级“承接上一段”），不写小镜头承接
    assert "承接上一镜结尾：赵虎俯身逼近，俯视林风，冷笑" in spans[1]
    # 尾态 = 上一镜动作结尾 + 表情；动作太长时只取最后一个分句
    assert "承接上一镜结尾：林风握紧扫帚，左手青铜古戒泛起暗红微光" not in spans[2]
    assert "承接上一镜结尾：左手青铜古戒泛起暗红微光，指节攥白" in spans[2]
    assert pic.startswith("承接上一段：两人相对而立")
    assert ST.beat_tail({"action": "他退后一步", "expression": "无"}) == "他退后一步"
    assert ST.beat_tail({}) == ""


def test_fixed_shot_says_no_push_pull_and_no_mirror_flip():
    pic = ST.compose_video_prompt(_seg())
    assert pic.count("固定镜头，不推拉、不摇移") == 2
    assert "人物左右站位与朝向全程不变" in pic
    forbid = VP.assemble_video_prompt(_seg(), []).split("【硬性禁区】")[1]
    assert "站位、朝向和左右位置前后一致，不镜像翻转" in forbid


def test_camera_and_composition_written_per_beat():
    pic = ST.compose_video_prompt(_seg())
    assert "中近景，林风右后方，与肩同高，平视，赵虎头肩加林风肩膀，背景朝向廊柱，固定镜头，不推拉、不摇移" in pic


# ---------- D. 特效边界 ----------
def test_fx_boundary_joined_only_when_present():
    pic = ST.compose_video_prompt(_seg())
    assert pic.count("特效边界：") == 1
    assert "特效边界：微光只亮在古戒上，持续两秒后收敛，不扩散到手臂和脸、不形成光球" in pic
    # 特效边界跟在它所属的小镜头里（第 2 个时间段），不在别的镜头
    second = pic.split("[4-9秒]")[1].split("[9-15秒]")[0]
    assert "特效边界：" in second
    no_fx = [dict(b, boundary="") for b in _beats()]
    assert "特效边界" not in ST.compose_video_prompt(_seg(beats=no_fx))
    # 动作有特效词却没写边界 → 提示
    assert ST.fx_boundary_warnings([_seg(beats=no_fx)]) == ["段 2 第 2 个小镜头有特效但没写边界（只出现在哪、不许怎样）"]
    assert ST.fx_boundary_warnings([_seg()]) == []


def test_fx_warning_reaches_upload_plan(tmp_path):
    no_fx = [dict(b, boundary="") for b in _beats()]
    plan = VP.build_upload_plan(_seg(beats=no_fx), [], [], [], tmp_path, FAST)
    assert any("有特效但没写边界" in w for w in plan["warnings"])


# ---------- E. 多场景图背景参考 ----------
def test_multi_scene_refs_tag_background_per_beat():
    refs = [{"type": "角色", "name": "赵虎", "path": "/s/a.png"},
            _scene_ref(1, "演武场·廊柱一侧"), _scene_ref(2, "演武场·雨幕一侧")]
    p = VP.assemble_video_prompt(_seg(), refs)
    pic = _picture(p)
    # 第 1 镜构图写了“廊柱”→ 图2；第 2 镜“雨幕”→ 图3；第 3 镜构图含“雨幕”→ 图3
    spans = [s for s in re.split(r"(?=\[\d+(?:\.\d+)?-\d+(?:\.\d+)?秒\])", pic) if s.startswith("[")]
    assert "背景参考【@图片2】" in spans[0] and "背景参考【@图片3】" not in spans[0]
    assert "背景参考【@图片3】" in spans[1] and "背景参考【@图片3】" in spans[2]
    assert "图2：场景演武场·廊柱一侧" in p and "图3：场景演武场·雨幕一侧" in p


def test_multi_scene_refs_fall_back_to_first_when_no_match():
    refs = [_scene_ref(1, "演武场·东侧"), _scene_ref(2, "演武场·西侧")]
    pic = _picture(VP.assemble_video_prompt(_seg(), refs))
    assert pic.count("背景参考【@图片1】") == 3 and "背景参考【@图片2】" not in pic
    # 视角写在 view 字段里也能匹配
    refs = [_scene_ref(1, "演武场", view="正门"), _scene_ref(2, "演武场", view="雨幕")]
    pic = _picture(VP.assemble_video_prompt(_seg(), refs))
    assert pic.count("背景参考【@图片2】") == 2 and pic.count("背景参考【@图片1】") == 1


def test_single_scene_ref_tagged_once_for_whole_segment():
    p = VP.assemble_video_prompt(_seg(), [_scene_ref(1, "演武场")])
    assert _picture(p).count("背景参考") == 1 and _picture(p).startswith("背景参考【@图片1】；")
    assert "背景参考" not in _picture(VP.assemble_video_prompt(_seg(), []))  # 没有场景图不写


# ---------- F. 总长预算 ----------
def test_prompt_budget_trims_picture_and_forbid_but_never_dialogue_or_hard(monkeypatch):
    seg = _seg()
    monkeypatch.setattr(VP, "MAX_PROMPT_CHARS", 10 ** 6)
    full, w = VP.assemble_video_prompt_ex(seg, [])
    assert w == [] and VP.TRIMMED_WARNING not in full
    limit = len(full) - 150
    monkeypatch.setattr(VP, "MAX_PROMPT_CHARS", limit)
    p, w = VP.assemble_video_prompt_ex(seg, [])
    assert VP.TRIMMED_WARNING in w and len(p) < len(full)
    # 对白清单整段、硬性参数原样保留
    assert full.split("【台词清单】")[1].split("\n")[0] == p.split("【台词清单】")[1].split("\n")[0]
    assert full.split("【硬性参数】")[1].split("\n")[0] == p.split("【硬性参数】")[1].split("\n")[0]
    # 第一步先去禁区里重复的套话（时长、水印在硬性参数里已有）
    forbid = p.split("【硬性禁区】")[1]
    assert "严格时长" not in forbid and "无水印" not in forbid and "同一角色只能出现一个实体" in forbid
    # 承接、台词序号、特效边界这些关键信息不被画面缩短裁掉
    monkeypatch.setattr(VP, "MAX_PROMPT_CHARS", 700)
    p, w = VP.assemble_video_prompt_ex(seg, [])
    assert VP.TRIMMED_WARNING in w
    assert p.count(A_LINE) == 1 and "此时赵虎说出台词①" in p and "特效边界：微光只亮在古戒上" in p
    assert "承接上一镜结尾" in p and "尾态：林风走进雨里" in p
    assert len(_picture(p)) < len(_picture(full))
    assert any("仍超出长度预算" in x for x in w)  # 700 字压不进去时明确告知，不静默超长


def test_budget_default_and_warning_in_upload_plan(tmp_path, monkeypatch):
    assert VP.MAX_PROMPT_CHARS == 1800
    plan = VP.build_upload_plan(_seg(), [], [], [], tmp_path, FAST)
    assert VP.TRIMMED_WARNING not in plan["warnings"] and len(plan["prompt"]) <= 1800
    monkeypatch.setattr(VP, "MAX_PROMPT_CHARS", 500)
    plan = VP.build_upload_plan(_seg(), [], [], [], tmp_path, FAST)
    assert VP.TRIMMED_WARNING == "提示词已按长度预算精简" and VP.TRIMMED_WARNING in plan["warnings"]


# ---------- G. 四格图兼容新字段 ----------
def test_storyboard_reads_new_beat_fields():
    from core.storyboard import storyboard_panels
    panels = storyboard_panels(_seg())
    assert len(panels) == 4
    assert "背景朝向廊柱" in panels[0]["text"] and "林风右后方，与肩同高，平视" in panels[0]["text"]
    # 旧 beats（没有 composition / boundary）照常
    old = [{k: v for k, v in b.items() if k not in ("composition", "boundary")} for b in _beats()]
    assert len(storyboard_panels(_seg(beats=old))) == 4
