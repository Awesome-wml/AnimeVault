"""视频段（T-203）：模板时长参数、段校正与拆段、滑块换算、五段式提示词、旧数据兼容、多句配音拼接；
T-211：整体设定（mood → 光影）、人物+表情说、景别自检"""
import shutil
import subprocess
from pathlib import Path

import pytest

from core import shot_split as SS
from core import shot_timing as ST
from core.llm_factory import safe_format
from core.prompt_tpl import SHOT_SPLIT_PROMPT
from core.providers import fake
from core.shot_voice import split_mixed_voice
from core.video_models import (DEFAULT_VIDEO_MODEL_KEY, VIDEO_MODELS, get_video_model, segment_budget,
                               segment_params)
from core.video_prompt import assemble_video_prompt, filter_refs, speaker_warnings
from core.video_slider import (arrow_steps, clamp_duration, duration_to_ratio, parse_duration_label, slider_x)
from core import tts_mix

FAST = get_video_model()


def _render(model, novel="一" * 230):
    return safe_format(SHOT_SPLIT_PROMPT, novel_paragraph=novel, style_block="", asset_block="", genre_rhythm="", chunk_note="",
                       **segment_params(model), **segment_budget(novel, model))


# ---------- 模型配置与模板 ----------
def test_video_models_config():
    keys = [m["key"] for m in VIDEO_MODELS]
    assert keys == ["seedance-2.0-fast", "seedance-2.0", "seedance-2.0-mini", "seedance-2.5"]
    assert DEFAULT_VIDEO_MODEL_KEY == "seedance-2.0-fast" and get_video_model("nope")["key"] == DEFAULT_VIDEO_MODEL_KEY
    assert [m["cost_multiplier"] for m in VIDEO_MODELS] == [1, 2, 1, 5]
    assert all(m["max_duration"] == 15 and m["min_duration"] == 4 for m in VIDEO_MODELS)
    assert "mp4" in FAST["reference_types"] and "mp4" not in get_video_model("seedance-2.5")["reference_types"]
    assert not any("mp3" in m["reference_types"] for m in VIDEO_MODELS)


def test_template_renders_model_duration_params():
    out = _render(FAST)
    assert "{" not in out.split("结构如下")[0]  # 占位符全部填上
    assert "Seedance 2.0 Fast" in out and "每次固定生成 15 秒" in out
    assert "约 49 到 58 个字" in out and "不超过 58 个字" in out and "大约拆成 4 段" in out
    # 精简输出（T-204）：模型不写时长、起止、video_prompt 等代码能推出来的字段
    example = out.split("结构如下")[1]
    assert '{"segments":[' in example and '"lines":["旁白：' in example and '|1"' in example
    for k in ('"duration"', '"video_prompt"', '"start"', '"fill_rate"', '"neg_prompt"', '"image_prompt"', '"segment_no"'):
        assert k not in example
    # 换模型（更短的上限）参数自动跟着变
    short = dict(FAST, name="测试模型", max_duration=10, min_duration=3)
    out2 = _render(short)
    assert "每次固定生成 10 秒" in out2 and "约 27 到 36 个字" in out2
    assert '"segments"' in out and "背景音乐" in out


# ---------- 段校正 ----------
def _seg(lines, duration=15, beats=None):
    return {"segment_no": 1, "duration": duration, "lines": lines, "beats": beats or []}


def test_lines_fixed_no_overlap_in_bounds():
    lines = [
        {"speaker": "旁白", "text": "暴雨压在林家演武场上，青石板被砸得白茫茫一片。", "kind": "narration", "start": 0, "end": 2},
        {"speaker": "赵虎", "text": "你也配站在这里？", "kind": "onscreen", "start": 1, "end": 30},  # 与上一句重叠
        {"speaker": "林风", "text": "“三个月后，我等你。”", "kind": "bogus", "start": 14.9},  # 越界、kind 非法、带引号
    ]
    out, notes = ST.normalize_segment(_seg(lines), FAST)
    assert notes == [] and len(out) == 1
    seg = out[0]
    got = seg["lines"]
    assert got[2]["text"] == "三个月后，我等你。" and got[2]["kind"] == "onscreen"
    for ln in got:  # 起止 = 朗读时长
        assert ln["end"] - ln["start"] == pytest.approx(ST.speech_seconds(ln["text"]), abs=0.11)
    assert all(got[i]["end"] <= got[i + 1]["start"] for i in range(2))
    assert got[-1]["end"] <= 15 - 0.3 + 1e-6 and got[0]["start"] >= 0
    assert seg["duration"] == 15 and 0 < seg["fill_rate"] < 1


def test_beats_share_line_timeline():
    lines = [{"speaker": "旁白", "text": "一二三四五六七八九十。" * 2, "kind": "narration", "start": 0.5},
             {"speaker": "甲", "text": "你来了。", "kind": "onscreen", "start": 3.0}]  # 与上一句重叠，会被顺延
    beats = [{"start": 0, "end": 4, "shot_size": "全景", "line_refs": [1]},
             {"start": 4, "end": 15, "shot_size": "近景", "line_refs": [2]}]
    seg = ST.normalize_segment(_seg(lines, beats=beats), FAST)[0][0]
    b2 = seg["beats"][1]
    assert b2["start"] <= seg["lines"][1]["start"] < b2["end"]  # 台词落在引用它的小镜头里
    assert seg["beats"][0]["start"] == 0 and seg["beats"][-1]["end"] == 15
    assert all(seg["beats"][i]["end"] == seg["beats"][i + 1]["start"] for i in range(len(seg["beats"]) - 1))


def test_over_budget_splits_at_sentence_boundary():
    # 约 159 字塞进 15 秒（需约 35 秒）：代码在句子边界拆段，每段不超台词预算
    sent = "陆川端着酒杯，神情轻松地在旁边听着包厢里的人说话。"
    lines = [{"speaker": "旁白", "text": sent * 3, "kind": "narration"},
             {"speaker": "陈子昂", "text": "你装得太用力了，想不注意都难。", "kind": "onscreen"},
             {"speaker": "旁白", "text": sent * 3, "kind": "narration"}]
    out, notes = ST.normalize_segment(_seg(lines), FAST)
    assert len(out) >= 3 and notes and "拆成" in notes[0]
    budget = ST.segment_capacity(FAST)
    for seg in out:
        assert ST.speech_total(seg["lines"]) <= budget + 1e-6
        assert seg["lines"][-1]["end"] <= seg["duration"] - 0.3 + 1e-6
        assert all(ln["text"].endswith(("。", "？")) for ln in seg["lines"])  # 只在句子边界切
        assert seg["split_by_code"] and "画外音" in seg["video_prompt"]
    joined = "".join(ln["text"] for seg in out for ln in seg["lines"])
    assert joined == "".join(ln["text"] for ln in lines)  # 一个字不丢、顺序不变


def test_short_scene_end_uses_actual_duration():
    seg = ST.normalize_segment({"lines": [{"speaker": "旁白", "text": "雨停了。"}]}, FAST)[0][0]
    assert seg["duration"] == 4  # 不足 6 秒取实际所需，且不少于模型最短
    seg = ST.normalize_segment({"duration": 15, "lines": [{"speaker": "旁白", "text": "雨停了。"}]}, FAST)[0][0]
    assert seg["duration"] == 15  # 模型补了反应镜头、写满 15 秒的照用


def test_rebalance_same_scene_uneven_segments():
    a = {"scene": "演武场，暴雨", "lines": [{"speaker": "旁白", "text": "雨很大。"}]}
    long_text = "赵虎冷笑一声，一脚踹在扫帚上，竹柄断成两截。" * 3
    b = {"scene": "演武场，雨幕", "lines": [{"speaker": "旁白", "text": long_text},
                                       {"speaker": "赵虎", "text": "就凭你？", "kind": "onscreen"}]}
    c = {"scene": "宿舍，深夜", "lines": [{"speaker": "旁白", "text": "夜深了。"}]}
    out, notes = ST.rebalance_segments([a, b, c], FAST)
    assert notes and "演武场" in notes[0]
    assert out[-1] is c  # 不同场景不动
    for seg in out[:-1]:
        assert ST.speech_total(ST.normalize_lines(seg["lines"])) <= ST.segment_capacity(FAST) + 1e-6


def test_retime_after_edit_and_legacy_fields():
    lines = [{"speaker": "旁白", "text": "雨很大。", "kind": "narration", "start": 0.5, "end": 1.4},
             {"speaker": "林风", "text": "来了。", "kind": "inner"},
             {"speaker": "赵虎", "text": "站住！", "kind": "onscreen"}]
    f = ST.retime_segment({"lines": lines, "duration": 15}, FAST)
    assert f["text"] == "雨很大。来了。站住！" and f["character_name"] == "赵虎" and not f["overflow"]
    f2 = ST.retime_segment({"lines": [{"speaker": "旁白", "text": "一二三四五。" * 20}], "duration": 15}, FAST)
    assert f2["overflow"] and f2["character_name"] == "旁白"


# ---------- 滑块换算（待真机验证的常量） ----------
def test_slider_conversion():
    assert clamp_duration(15) == 15 and clamp_duration(99) == 15 and clamp_duration(1) == 4 and clamp_duration("x") == 15
    assert duration_to_ratio(15) == 1 and duration_to_ratio(4) == 0
    assert slider_x(15) == 925  # 实测：拖到 925 为 15s
    assert slider_x(4, 600, 900, 4, 15) == 600 and slider_x(15, 600, 900, 4, 15) == 900
    assert slider_x(10, 600, 900, 4, 15) == 763.6 and slider_x(9.6, 600, 900, 4, 15) == 763.6  # 取整到秒
    assert 685 < slider_x(10) < 925
    assert parse_duration_label("15s") == 15 and parse_duration_label("10 秒") == 10 and parse_duration_label("自动") is None
    assert arrow_steps(12, 15) == 3 and arrow_steps(None, 15) == 0


# ---------- 五段式提示词 ----------
def test_assemble_video_prompt_five_sections_and_refs():
    seg = dict(fake.FAKE_SEGMENTS[1], shot_no=2)
    seg = ST.normalize_segment(seg, FAST)[0][0]
    refs = [{"type": "分镜参考", "name": "段首画面", "path": "/s/shot.png"},
            {"type": "角色", "name": "赵虎", "path": "/s/zh.png"},
            {"type": "角色", "name": "林风", "path": "/s/lf.webp"},
            {"type": "道具", "name": "青铜古戒", "path": "/s/ring.jpg"},
            {"type": "角色", "name": "音频", "path": "/s/a.mp3"}]
    refs = filter_refs(refs, FAST)
    assert len(refs) == 4  # 音频不上传
    p = assemble_video_prompt(seg, refs)
    heads = [ln.split("】")[0] + "】" for ln in p.split("\n")]
    assert heads == ["【整体设定】", "【硬性参数】", "【参考素材】", "【画面】", "【台词与旁白】", "【硬性禁区】"]
    assert "SEG002" in p and p.count("严格时长 15 秒") == 2 and p.count("无水印") == 2
    assert "图2：角色赵虎（主讲" in p and "图4：道具青铜古戒" in p
    assert "赵虎【@图片2】" in p and "林风【@图片3】" in p and "【@图片2】【@图片" not in p
    from core.video_prompt import _tag_names
    assert _tag_names("萧尘抬头；萧尘（平静）说：赵虎，我记下了；赵虎冷笑", {"萧尘": 2, "赵虎": 3}) == \
        "萧尘【@图片2】抬头；萧尘【@图片2】（平静）说：赵虎，我记下了；赵虎【@图片3】冷笑"  # 台词里的名字不动
    # 画内台词“人物+表情说：台词”：表情来自引用这句的小镜头（FAKE_SEGMENTS[1] 第一镜没写表情 → 退回 mood），原文不动
    assert "[0.5-2.1秒]赵虎紧张地说：你也配站在这里？（赵虎露脸" in p
    assert "画外音，画面人物不张嘴" in p
    forbid = p.split("【硬性禁区】")[1]
    assert "背景音乐" in forbid and "同一角色只能出现一个实体" in forbid and "群演" in forbid
    # 有台词却没参考图的角色要报告
    assert speaker_warnings(seg, refs[:1]) == ["赵虎 有画内台词但没有参考图"]


def test_overall_setting_has_mood_and_lighting():
    """【整体设定】= 画面人物（名字）+ 时辰 + 环境 + 光影（按 mood 映射，题材可覆盖）+ 情绪基调。"""
    from core.genre_rhythm import DEFAULT_LIGHTING, lighting_for_mood
    from core.video_prompt import overall_setting, time_of_day
    seg = ST.normalize_segment(dict(fake.FAKE_SEGMENTS[1], scene="暴雨萧瑟演武场，雨夜，对峙", shot_no=2), FAST)[0][0]
    setting = overall_setting(seg)
    assert setting.startswith("画面人物：赵虎、林风、苏婉；时辰：雨夜；环境：暴雨萧瑟演武场，雨夜，对峙；光影：")
    assert "冷白顶光" in setting and setting.endswith("情绪基调：紧张")  # 紧张 → 压抑/争吵一类的冷白顶光
    # 光影映射：四类基础情绪 + 题材覆盖 + 不认识的情绪用默认
    assert "冷白顶光" in lighting_for_mood("压抑") and "冷白顶光" in lighting_for_mood("争吵")
    assert "暖黄" in lighting_for_mood("温情") and "暖黄" in lighting_for_mood("和解")
    assert "清晨明亮日光" in lighting_for_mood("决绝") and "清晨明亮日光" in lighting_for_mood("离开")
    assert "暗部侧光" in lighting_for_mood("悬疑") and "暗部侧光" in lighting_for_mood("暗流涌动")
    assert lighting_for_mood("压抑", "悬疑") == "暗部侧光加冷白顶光，人物半身在阴影里"
    assert lighting_for_mood("压抑", "都市言情") == lighting_for_mood("压抑")  # 题材没有覆盖表 → 通用表
    assert lighting_for_mood("莫名其妙") == DEFAULT_LIGHTING and lighting_for_mood("") == DEFAULT_LIGHTING
    assert time_of_day("云顶会所顶层包厢，深夜，暖光转冷") == "深夜" and time_of_day("雨夜老宅书房") == "雨夜"
    assert time_of_day("会所包厢，冷灰") == ""
    # 整体设定进完整提示词的第一行；题材覆盖通过 genre 透传；人物名也打上图号
    p = assemble_video_prompt(seg, [{"type": "角色", "name": "赵虎", "path": "/s/zh.png"}], genre="悬疑")
    first = p.split("\n")[0]
    assert first.startswith("【整体设定】画面人物：赵虎【@图片1】、林风、苏婉；") and "暗部侧光加冷白顶光" in first
    assert "情绪基调：紧张" in first
    # 风格后缀：有就单独一行【风格】放在画面之后、台词之前；没有就不写
    assert "【风格】" not in p
    ps = assemble_video_prompt(seg, [], genre="悬疑", style_suffix="真人实拍电影级写实质感，冷色压抑")
    lines = ps.split("\n")
    assert "【风格】真人实拍电影级写实质感，冷色压抑" in lines
    assert lines.index("【风格】真人实拍电影级写实质感，冷色压抑") == lines.index(next(l for l in lines if l.startswith("【画面】"))) + 1
    # 表情优先于 mood：小镜头写了表情就用“人物+表情说：”
    seg2 = dict(seg, beats=[dict(seg["beats"][0], expression="冷笑")])
    assert "赵虎冷笑说：你也配站在这里？" in assemble_video_prompt(seg2, [])
    long_expr = dict(seg, beats=[dict(seg["beats"][0], expression="眼眶泛红却死死咬住下唇")])
    assert "赵虎眼眶泛红却死死咬住下唇，说：你也配站在这里？" in assemble_video_prompt(long_expr, [])
    assert ST.speak_tag("陆川", {}, "") == "陆川说：" and ST.speak_tag("陈子昂", {}, "步步紧逼") == "陈子昂（步步紧逼）说："
    # 小镜头拍的是别人的反应（动作里只有陆川）：表情不属于说话人陈子昂，退回 mood；动作里有说话人就照用
    react = {"action": "陆川抬手想插话，指尖停在半空", "expression": "喉结滚动，眼神躲闪"}
    assert ST.speak_tag("陈子昂", react, "紧逼", ["陆川", "陈子昂"]) == "陈子昂紧逼地说："
    assert ST.speak_tag("陆川", react, "紧逼", ["陆川", "陈子昂"]) == "陆川喉结滚动，眼神躲闪说："
    assert ST.speak_tag("陈子昂", {"action": "镜头扫过桌面", "expression": "冷笑"}, "", ["陆川", "陈子昂"]) == "陈子昂冷笑说："
    assert "冷白顶光" in lighting_for_mood("步步紧逼")
    # 无人物、没时辰的段也能组装
    bare = {"lines": [{"speaker": "旁白", "text": "空镜。", "kind": "narration", "start": 0, "end": 1}], "scene": "荒原"}
    assert overall_setting(bare) == f"画面人物：无人物，纯环境；环境：荒原；光影：{DEFAULT_LIGHTING}；情绪基调：按台词与动作自然呈现"


def test_same_shot_size_three_in_a_row_warns():
    """连续 3 个小镜头同一景别（跨段也算）→ 告警；拆分镜的 notes 与生成时的 warnings 都带上。"""
    from core.video_prompt import build_upload_plan
    b = lambda size, i: {"shot_size": size, "camera": "平视", "move": "固定", "action": f"动作{i}", "line_refs": [i]}
    segs = [{"shot_no": 1, "beats": [b("中景", 1), b("中景", 2)]},
            {"shot_no": 2, "beats": [b("中景", 1), b("特写", 2), b("近景", 3), b("近景", 4), b("近 景", 5)]}]
    warns = ST.shot_size_warnings(segs)
    assert len(warns) == 2
    assert warns[0].startswith("从段 1 第 1 个小镜头起连续 3 个小镜头都是中景") and "景别要有变化" in warns[0]
    assert warns[1].startswith("从段 2 第 3 个小镜头起连续 3 个小镜头都是近景")
    assert ST.shot_size_warnings([{"beats": [b("中景", 1), b("特写", 2), b("中景", 3), b("中景", 4)]}]) == []
    assert ST.shot_size_warnings([{"beats": [b("", 1), b("", 2), b("", 3)]}]) == []  # 没写景别不算
    # 拆分镜落库：build_segments 把告警放进 notes
    from api.shot import build_segments
    items = [SS.expand_segment(x, {"林风", "赵虎", "苏婉"}, {"青铜古戒"}) for x in fake.FAKE_SEGMENTS_COMPACT]
    items[0]["beats"] = [dict(x, shot_size="中景") for x in items[0]["beats"]]
    _, notes = build_segments(items, FAST, {"林风", "赵虎", "苏婉"}, {"青铜古戒"})
    assert any("连续 3 个小镜头都是中景" in n for n in notes)
    # 生成视频时：本段内连续同景别进 warnings
    seg = ST.normalize_segment(dict(fake.FAKE_SEGMENTS[2], shot_no=3), FAST)[0][0]
    seg["beats"] = [dict(x, shot_size="特写") for x in seg["beats"]]
    plan = build_upload_plan(seg, [], [], [], Path("/nonexistent"), FAST)
    assert any("连续 3 个小镜头都是特写" in w for w in plan["warnings"])
    assert plan["prompt"].startswith("【整体设定】画面人物：林风、赵虎；")


# ---------- 旧数据兼容 ----------
def test_legacy_mixed_voice_split_only_for_old_format():
    old = [{"shot_no": 1, "character_name": "旁白", "text": "赵虎脸色铁青：你藏了什么？"}]
    assert len(split_mixed_voice(old, {"赵虎"})) == 2
    seg = [{"shot_no": 1, "text": "赵虎脸色铁青：你藏了什么？", "lines": [{"speaker": "旁白", "text": "x"}]}]
    assert split_mixed_voice(seg, {"赵虎"}) == seg  # 视频段不误拆
    assert ST.is_segment(fake.FAKE_SEGMENTS[0]) and not ST.is_segment(fake.FAKE_SHOTS[0])


# ---------- 多句配音拼接 ----------
@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="需要 ffmpeg")
def test_tts_mix_multi_lines():
    assert tts_mix.plan_placements([0.5, 1.0, 5.0], [2.0, 1.0, 1.0]) == [0.5, 2.65, 5.0]
    clip = fake.speech_bytes()
    data, timeline = tts_mix.mix_lines([clip, clip], [0.5, 6.0], 15)
    assert len(timeline) == 2 and timeline[0]["start"] == 0.5 and timeline[1]["start"] >= timeline[0]["end"]
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", "-"],
                       input=data, capture_output=True)
    total = float(r.stdout.strip())
    assert 14.5 <= total <= 15.6  # 补齐到段时长


# ---------- 接口：项目视频模型、旧版模板兼容 ----------
def test_project_video_model_and_config(client, project):
    h, pid = project["user"]["headers"], project["id"]
    models = client.get("/api/config/video-models").json()["data"]
    assert models["default"] == "seedance-2.0-fast" and len(models["models"]) == 4
    assert client.get(f"/api/projects/{pid}", headers=h).json()["video_model"] == "seedance-2.0-fast"
    assert client.put(f"/api/projects/{pid}", json={"video_model": "seedance-2.5"}, headers=h).status_code == 200
    assert client.get(f"/api/projects/{pid}", headers=h).json()["video_model"] == "seedance-2.5"
    assert client.put(f"/api/projects/{pid}", json={"video_model": "nope"}, headers=h).status_code == 400
    # 拆出来的段记下所用模型
    r = client.post("/api/shots/split", json={"project_id": pid, "novel_paragraph": "林风与赵虎在演武场对峙。"}, headers=h)
    assert r.status_code == 200 and r.json()["data"]["format"] == "segment"
    shots = client.get("/api/shots", params={"project_id": pid}, headers=h).json()
    assert {s["model_key"] for s in shots} == {"seedance-2.5"}
    assert shots[1]["final_video_prompt"].startswith("【整体设定】画面人物：赵虎、林风；")
    assert "\n【硬性参数】段号 SEG002" in shots[1]["final_video_prompt"]


def test_legacy_template_still_works(client, project):
    """用户自定义的旧版拆分镜模板（输出 shots，一镜一声）：照旧落库，旁白/台词混合仍会拆开"""
    h, pid = project["user"]["headers"], project["id"]
    r = client.post("/api/prompts", json={"name": "旧版拆分镜", "type": "split_shots", "category": "通用",
                                          "content": '旧模板 {novel_paragraph}\nJSON 结构如下：{{"shots": []}}'}, headers=h)
    prompt_id = r.json()["id"]
    try:
        r = client.post("/api/shots/split", json={"project_id": pid, "novel_paragraph": "林风与赵虎对峙。",
                                                  "prompt_id": prompt_id}, headers=h)
        assert r.status_code == 200, r.text
        assert r.json()["data"]["format"] == "legacy" and r.json()["data"]["count"] == 3
        shots = client.get("/api/shots", params={"project_id": pid}, headers=h).json()
        assert shots[1]["text"] == "你也配站在这里？" and shots[1]["character_name"] == "赵虎"
        assert shots[1]["lines"] is None and shots[1]["fill_rate"] is None and "final_video_prompt" not in shots[1]
        # 旧数据配音：整段一个声音
        r = client.post("/api/tts/generate", json={"shot_id": shots[1]["id"], "text": shots[1]["text"]}, headers=h)
        assert r.status_code == 200 and r.json()["data"]["lines"] == 1 and r.json()["data"]["timeline"] is None
    finally:
        client.delete(f"/api/prompts/{prompt_id}", headers=h)



def test_trim_invented_tail_and_duplicates():
    novel = "陆川僵坐在沙发上。那一晚之后，陆川的人设还是塌了。活得很狼狈，也活得清醒。"
    items = [
        {"lines": [{"speaker": "旁白", "text": "陆川僵坐在沙发上。"}, {"speaker": "旁白", "text": "那一晚之后，陆川的人设还是塌了。"},
                   {"speaker": "旁白", "text": "活得很狼狈，也活得清醒。"}]},
        {"lines": [{"speaker": "旁白", "text": "活得很狼狈，也活得清醒。"}, {"speaker": "旁白", "text": "他缓缓摘下手表放在桌上。"}],
         "beats": [{"start": 0, "end": 15, "line_refs": [1, 2]}]},
        {"lines": [{"speaker": "旁白", "text": "包厢里一片寂静，众人面面相觑。"}]},
    ]
    out, notes = ST.trim_invented_tail(items, novel)
    assert len(out) == 1 and len(out[0]["lines"]) == 3 and len(notes) == 3
    # 中间被合规改写、原文找不到的句子不删
    mid = [{"lines": [{"speaker": "旁白", "text": "一句改写过的话放在中间。"}, {"speaker": "旁白", "text": "陆川僵坐在沙发上。"}]}]
    assert ST.trim_invented_tail(mid, novel)[0] == mid
    # 原文和台词完全对不上时不删编造句（防误伤），只去掉紧挨着重复的那句
    kept, notes2 = ST.trim_invented_tail(items, "一段完全不同的小说")
    assert sum(len(x["lines"]) for x in kept) == 5 and len(notes2) == 1 and "重复" in notes2[0]
