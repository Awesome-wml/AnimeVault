"""提示词能力表（core/prompt_profiles）与成片回看（core/video_review）。"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from core import prompt_profiles as PP
from core import video_prompt as VP
from core import video_review as VR
from core.shot_timing import (beat_rhythm_warnings, compose_video_prompt, normalize_beats, normalize_lines,
                              normalize_segment, time_lines)
from core.video_models import VIDEO_MODELS, get_video_model

FIXTURE = Path(__file__).parent / "fixtures" / "storyboard_regression_52.json"
FAST = get_video_model("seedance-2.0-fast")
LEAN = PP.PROFILES["seedance2-lean"]


def _seg(n):
    seg = json.loads(FIXTURE.read_text(encoding="utf-8"))[n - 1]
    out, _ = normalize_segment(dict(seg, model_key=FAST["key"]), FAST)
    return dict(out[0], shot_no=n, model_key=FAST["key"])


# ---------- 能力表 ----------
def test_every_model_points_at_a_known_profile():
    for m in VIDEO_MODELS:
        assert m["prompt_profile"] in PP.PROFILES
    assert PP.profile_for(FAST).key == "seedance2" and PP.profile_for("seedance-2.5").key == "seedance2"
    assert PP.profile_for(None).key == PP.DEFAULT_PROFILE_KEY and PP.profile_for("没有这个模型").key == "seedance2"


def test_env_override_switches_profile_for_ab_runs(monkeypatch):
    monkeypatch.setenv(PP.ENV_OVERRIDE, "seedance2-lean")
    assert PP.profile_for(FAST).key == "seedance2-lean"
    monkeypatch.setenv(PP.ENV_OVERRIDE, "写错了")
    assert PP.profile_for(FAST).key == "seedance2"          # 写错的名字不生效，不会悄悄换写法


def test_beat_cap_comes_from_profile():
    lines = normalize_lines([{"speaker": "旁白", "text": "雨" * 30 + "。", "kind": "narration"},
                             {"speaker": "旁白", "text": "风" * 30 + "。", "kind": "narration"}])
    time_lines(lines, 15)
    raw = [{"shot_size": "中景", "action": "雨落长街", "line_refs": [1]}, {"shot_size": "近景", "action": "风过檐角", "line_refs": [2]}]
    default = normalize_beats(raw, 15, 2, lines=lines)
    lean = normalize_beats(raw, 15, 2, lines=lines, max_beat=LEAN.max_beat_seconds)
    assert max(b["end"] - b["start"] for b in default) <= 8.0 and len(default) == 2
    assert max(b["end"] - b["start"] for b in lean) <= 5.0 + 0.05 and len(lean) > len(default)
    assert lean[0]["start"] == 0 and lean[-1]["end"] == 15
    assert all(a["end"] == b["start"] for a, b in zip(lean, lean[1:]))


def test_default_profile_renders_exactly_as_before():
    seg = _seg(5)
    assert compose_video_prompt(seg, PP.PROFILES["seedance2"]) == compose_video_prompt(seg) == seg["video_prompt"]
    p = VP.assemble_video_prompt(seg, [], style_suffix="3D 国漫风格")
    heads = [h for h in ("【整体设定】", "【硬性参数】", "【台词清单】", "【画面】", "【风格】", "【硬性禁区】")]
    assert [p.index(h) for h in heads] == sorted(p.index(h) for h in heads)
    assert "禁止白模" in p and "[镜头1 " not in p


def test_lean_profile_reorders_labels_shots_and_shortens_constraints():
    seg = _seg(5)
    full = VP.assemble_video_prompt(seg, [], style_suffix="3D 国漫风格")
    lean = VP.assemble_video_prompt(seg, [], style_suffix="3D 国漫风格", profile=LEAN)
    assert lean.startswith("【风格】")                                   # 画风锚定放最前
    assert lean.index("【画面】") < lean.index("【台词清单】") < lean.index("【硬性禁区】")
    assert "[镜头1 0-" in lean and "[镜头2 " in lean
    forbid = lean.split("【硬性禁区】")[1]
    assert forbid.count("；") + 1 == len(VP.LEAN_FORBID) <= 5 and "禁止" not in forbid
    assert len(lean) < len(full)
    for ln in seg["lines"]:                                               # 换写法不丢台词
        assert ln["text"] in lean


def test_hand_edited_picture_is_never_rerendered():
    seg = dict(_seg(5))
    seg["video_prompt"] = seg["video_prompt"].replace("雨水冲刷刀身", "用户手工改过的动作")
    lean = VP.assemble_video_prompt(seg, [], profile=LEAN)
    assert "用户手工改过的动作" in lean and "[镜头1 " not in lean


def test_too_many_action_clauses_and_too_many_beats_are_flagged():
    seg = {"shot_no": 3, "beats": [
        {"start": 0, "end": 3, "action": "沈砚指腹抹去灰纸，药丸滚入掌心，仰头吞下，喉结一滚"},
        {"start": 3, "end": 6, "action": "他缓缓抬头"}]}
    notes = beat_rhythm_warnings([seg])
    assert any("第 1 个小镜头的动作有 4 个分句" in n for n in notes) and not any("第 2 个小镜头的动作" in n for n in notes)
    many = {"shot_no": 4, "beats": [{"start": i * 2, "end": i * 2 + 2, "action": "走"} for i in range(6)]}
    assert any("有 6 个小镜头" in n for n in beat_rhythm_warnings([many]))


def test_consistency_warning_for_silent_character_without_reference():
    shot = {"characters": ["沈砚", "铁面具"], "lines": [{"speaker": "铁面具", "text": "找死！", "kind": "onscreen"}]}
    assert VP.consistency_warnings(shot, []) == ["沈砚 出镜但没有参考图，各段长相无法保持一致，建议先出角色图"]
    assert VP.consistency_warnings(shot, [{"type": "角色", "name": "沈砚"}]) == []


# ---------- 成片回看 ----------
def test_compare_cuts_finds_the_extra_cut_from_the_real_first_clip():
    """第 1 段真实成片：提示词在 10、12.5 秒切，成片切在 4.75、10.58、12.75 秒——4.75 是模型自己补的。"""
    beats = [{"start": 0, "end": 10}, {"start": 10, "end": 12.5}, {"start": 12.5, "end": 15}]
    r = VR.review(beats, [4.75, 10.58, 12.75], 15.07, 15)
    assert r["extra"] == [4.75] and r["missing"] == [] and r["matched"] == 2 and not r["ok"]
    assert "写了 3 个小镜头，成片切了 4 个" in r["notes"][0] and "4.75" in r["notes"][0]
    assert r["longest_shot_seconds"] == 5.8


def test_review_reports_missing_cut_and_wrong_duration_and_clean_pass():
    beats = [{"start": 0, "end": 5}, {"start": 5, "end": 10}, {"start": 10, "end": 15}]
    r = VR.review(beats, [5.2], 10.0, 15)
    assert r["missing"] == [10.0] and any("没有切" in n for n in r["notes"]) and any("成片 10.0 秒" in n for n in r["notes"])
    ok = VR.review(beats, [4.6, 10.3], 15.0, 15)
    assert ok["ok"] and ok["notes"] == []
    s = VR.summarize([r, ok, {"error": "x", "ok": None}, None])
    assert s == {"reviewed": 2, "as_planned": 1, "with_extra_cuts": 0, "with_missing_cuts": 1, "longest_shot_seconds": 5.7}


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="需要 ffmpeg")
def test_detect_cuts_on_a_generated_clip(tmp_path, monkeypatch):
    monkeypatch.setenv("DONGAI_FFMPEG_BIN", shutil.which("ffmpeg"))
    clip = tmp_path / "videos" / "c.mp4"
    clip.parent.mkdir()
    parts = ";".join(f"color=c={c}:s=160x90:d={d}:r=24[v{i}]" for i, (c, d) in enumerate((("red", 3), ("blue", 4), ("green", 2))))
    subprocess.run([shutil.which("ffmpeg"), "-v", "error", "-y", "-f", "lavfi", "-i", "anullsrc", "-filter_complex",
                    parts + ";[v0][v1][v2]concat=n=3:v=1:a=0[v]", "-map", "[v]", "-t", "9", str(clip)], check=True)
    assert VR.detect_cuts(clip) == pytest.approx([3.0, 7.0], abs=0.1)
    shot = {"video_path": "videos/c.mp4", "duration": 9,
            "beats": [{"start": 0, "end": 3}, {"start": 3, "end": 9}]}
    r = VR.review_video(shot, tmp_path)
    assert r["extra"] == pytest.approx([7.0], abs=0.1) and r["video_path"] == "videos/c.mp4"
    assert VR.review_video({"video_path": "videos/没有.mp4"}, tmp_path) is None


# ---------- 语速进能力表 ----------
def test_speech_rate_comes_from_profile_and_is_scoped(monkeypatch):
    import dataclasses
    from core import pacing
    from core.shot_timing import speech_seconds
    from core.video_models import segment_budget, segment_params
    text = "雨" * 30
    assert pacing.current_rate() == pacing.CHARS_PER_SECOND == 5.0 and speech_seconds(text) == 6.0
    with pacing.use_rate(4.0):
        assert speech_seconds(text) == 7.5 and pacing.chars_for_seconds(13) == 52
        with pacing.use_rate(None):
            assert speech_seconds(text) == 6.0                       # None = 全局缺省
        assert speech_seconds(text) == 7.5
    assert speech_seconds(text) == 6.0                               # 出了作用域恢复

    slow = dataclasses.replace(PP.PROFILES["seedance2"], chars_per_second=4.0)
    monkeypatch.setitem(PP.PROFILES, "seedance2", slow)
    assert pacing.rate_for(FAST) == 4.0 and pacing.rate_for("seedance-2.5") == 4.0
    params = segment_params(FAST)
    assert params["chars_per_second"] == "4" and params["chars_high"] == 13 * 4 and params["chars_low"] == 11 * 4
    assert segment_budget("雨" * 520, FAST)["novel_seconds"] == 130
    # 同一段台词：语速慢了，朗读时间变长，原来装得下的现在要拆
    lines = [{"speaker": "旁白", "text": "雨" * 22 + "。", "kind": "narration"},
             {"speaker": "旁白", "text": "风" * 22 + "。", "kind": "narration"},
             {"speaker": "旁白", "text": "夜" * 23 + "。", "kind": "narration"}]
    out, _ = normalize_segment({"lines": lines, "beats": [], "duration": 15}, FAST)
    assert len(out) == 2 and pacing.current_rate() == 5.0            # 入口自己设语速，用完恢复


def test_default_rate_unchanged_for_all_models():
    from core import pacing
    for m in VIDEO_MODELS:
        assert pacing.rate_for(m) == 5.0


# ---------- 从回看结果里学小镜头上限 ----------
def _rev(beats):
    return {"ok": not any(c for _, c in beats), "beats": [{"seconds": sec, "cut_inside": c} for sec, c in beats]}


def test_review_records_which_planned_beat_got_an_extra_cut():
    beats = [{"start": 0, "end": 10}, {"start": 10, "end": 12.5}, {"start": 12.5, "end": 15}]
    r = VR.review(beats, [4.75, 10.58, 12.75], 15.07, 15)
    assert r["beats"] == [{"seconds": 10.0, "cut_inside": True}, {"seconds": 2.5, "cut_inside": False},
                          {"seconds": 2.6, "cut_inside": False}]


def test_learned_cap_needs_enough_samples_and_points_at_the_failing_length():
    few = [_rev([(7.5, True), (3.0, False)])] * 2
    assert VR.learned_beat_cap(few) is None                                   # 样本不够：不下结论
    # 5～6 秒的撑得住；7～8 秒的 5 个里 3 个被多切
    data = [_rev([(5.5, False), (7.5, True)]), _rev([(5.2, False), (7.8, True)]), _rev([(5.9, False), (7.2, True)]),
            _rev([(5.4, False), (7.6, False)]), _rev([(6.0, False), (7.4, False)])]
    got = VR.learned_beat_cap(data)
    assert got["max_beat_seconds"] == 7.0 and got["samples"] == 10 and "7～8 秒的小镜头 5 个里有 3 个" in got["evidence"]
    fine = [_rev([(5.5, False), (7.5, False)])] * 6
    assert VR.learned_beat_cap(fine) is None                                  # 都撑得住：不动
    assert VR.learned_beat_cap(data, ceiling=7.0) is None                     # 学到的不比现有上限更紧：不动
    assert VR.learned_beat_cap([{"error": "x", "ok": None}, None, "x"]) is None


def test_learned_cap_tightens_beat_splitting():
    from core.shot_timing import _beat_cap
    assert _beat_cap(FAST) == 8.0
    assert _beat_cap(dict(FAST, learned_max_beat_seconds=6.0)) == 6.0
    assert _beat_cap(dict(FAST, learned_max_beat_seconds=20)) == 8.0          # 只会更紧，不会放宽
    assert _beat_cap(dict(FAST, learned_max_beat_seconds=1)) == 8.0           # 离谱的值不用
    lines = [{"speaker": "旁白", "text": "雨" * 36 + "。", "kind": "narration"},
             {"speaker": "旁白", "text": "风" * 20 + "。", "kind": "narration"}]
    beats = [{"shot_size": "中景", "action": "雨落长街", "line_refs": [1]}, {"shot_size": "近景", "action": "风过檐角", "line_refs": [2]}]
    normal = normalize_segment({"lines": lines, "beats": beats, "duration": 15}, FAST)[0][0]
    tight = normalize_segment({"lines": lines, "beats": beats, "duration": 15}, dict(FAST, learned_max_beat_seconds=5.0))[0][0]
    assert max(b["end"] - b["start"] for b in tight["beats"]) <= 5.05 < max(b["end"] - b["start"] for b in normal["beats"])


# ---------- 看图检查内容（可选） ----------
def test_vision_messages_and_notes():
    beats = [{"shot_size": "特写", "composition": "侧脸与刀锋", "action": "刀锋贴耳掠过", "start": 0, "end": 3},
             {"shot_size": "中景", "action": "黑衣人倒下", "start": 3, "end": 6}]
    msgs = VR.vision_messages(beats, [b"\xff\xd8a", b"\xff\xd8b"])
    parts = msgs[0]["content"]
    assert parts[0]["type"] == "text" and "镜头 1：特写，侧脸与刀锋，刀锋贴耳掠过" in parts[0]["text"]
    assert [p["type"] for p in parts[1:]] == ["image_url", "image_url"]
    assert parts[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    raw = {"frames": [{"no": 1, "people": 1, "has_text": True, "match": "相符", "problem": ""},
                      {"no": 2, "people": 3, "has_text": False, "match": "不符", "problem": "画面里是三个人站着，没有人倒下"},
                      {"no": 9, "has_text": True}, "x"]}
    assert VR.vision_notes(raw, 2) == ["成片看图：第 1 个小镜头画面里出现了文字或字幕",
                                       "成片看图：第 2 个小镜头与描述不符——画面里是三个人站着，没有人倒下"]
    assert VR.vision_notes("乱回", 2) == VR.vision_notes({"frames": "x"}, 2) == []


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="需要 ffmpeg")
def test_review_content_extracts_one_frame_per_beat_and_survives_errors(tmp_path, monkeypatch):
    import asyncio
    monkeypatch.setenv("DONGAI_FFMPEG_BIN", shutil.which("ffmpeg"))
    clip = tmp_path / "videos" / "c.mp4"
    clip.parent.mkdir()
    subprocess.run([shutil.which("ffmpeg"), "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=red:s=160x90:d=6:r=24",
                    str(clip)], check=True)
    shot = {"video_path": "videos/c.mp4", "beats": [{"start": 0, "end": 3, "action": "甲"}, {"start": 3, "end": 6, "action": "乙"}]}

    class Vision:
        def __init__(self, reply):
            self.reply, self.seen = reply, None

        async def chat_json(self, messages, max_tokens=None):
            self.seen = messages
            if isinstance(self.reply, Exception):
                raise self.reply
            return self.reply

    llm = Vision({"frames": [{"no": 2, "has_text": True}]})
    out = asyncio.run(VR.review_content(llm, shot, tmp_path))
    assert out == {"notes": ["成片看图：第 2 个小镜头画面里出现了文字或字幕"], "frames": 2}
    assert len(llm.seen[0]["content"]) == 3
    assert asyncio.run(VR.review_content(Vision(RuntimeError("模型不支持图片")), shot, tmp_path))["notes"] == []
    assert asyncio.run(VR.review_content(llm, {"video_path": "videos/c.mp4", "beats": []}, tmp_path)) is None
