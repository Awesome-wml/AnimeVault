"""分镜回归集：一部真实小说（约 3000 字）拆出的 52 段分镜原始数据（模型给的台词与小镜头，未带时间）。

换视频模型、改提示词模板或改时间分配逻辑后跑这一组，守住成片回看时踩过的坑。只断言“不能再出现”的东西，
不断言具体措辞，模板可以自由演进。新踩到的坑在这里加一条断言。
"""
import json
from pathlib import Path

import pytest

from core.bystander import beat_phrases
from core.shot_timing import MAX_BEAT_SECONDS, MIN_BEAT_SECONDS, normalize_beats, normalize_lines, time_lines
from core.video_prompt import character_detail, overall_setting

FIXTURE = Path(__file__).parent / "fixtures" / "storyboard_regression_52.json"


@pytest.fixture(scope="module")
def segments():
    segs = json.loads(FIXTURE.read_text(encoding="utf-8"))
    for s in segs:
        lines = normalize_lines(s["lines"])
        s["overflow"] = time_lines(lines, s["duration"])
        s["lines"] = lines
        s["beats"] = normalize_beats(s["beats"], s["duration"], len(lines), lines=lines)
    return segs


def test_fixture_is_the_full_set(segments):
    assert len(segments) == 52


def test_no_beat_longer_than_cap_or_shorter_than_floor(segments):
    for s in segments:
        assert s["beats"][0]["start"] == 0 and s["beats"][-1]["end"] == s["duration"]
        for b in s["beats"]:
            d = b["end"] - b["start"]
            assert d <= MAX_BEAT_SECONDS + 0.05, (s["shot_no"], b)
            assert d >= MIN_BEAT_SECONDS - 0.05 or len(s["beats"]) == 1, (s["shot_no"], b)


def test_renormalizing_is_stable(segments):
    for s in segments:
        again = normalize_beats(s["beats"], s["duration"], len(s["lines"]), lines=s["lines"])
        assert [(b["start"], b["end"]) for b in again] == [(b["start"], b["end"]) for b in s["beats"]], s["shot_no"]


def test_onscreen_line_stays_inside_its_speaker_beats(segments):
    """画内对白说完之前，画面不切到没有这句台词的小镜头上（装不下 15 秒的段除外，那是装段问题）。"""
    for s in segments:
        if s["overflow"]:
            continue
        for i, ln in enumerate(s["lines"], start=1):
            if ln["kind"] != "onscreen":
                continue
            owners = [k for k, b in enumerate(s["beats"]) if i in b["line_refs"]]
            if not owners:
                continue
            k = owners[0]
            while k + 1 < len(s["beats"]) and s["beats"][k + 1].get("auto_split"):
                k += 1
            assert ln["end"] <= s["beats"][k]["end"] + 0.25, (s["shot_no"], i)


def test_bystander_filler_never_contradicts_the_scene(segments):
    for s in segments:
        phrases = beat_phrases(s)
        for b, ph in zip(s["beats"], phrases):
            if "空镜" in b["shot_size"] and not b.get("others"):
                assert ph == "", s["shot_no"]
            for banned in ("手中兵器", "椅背", "桌沿", "杯中", "理了理衣袖", "戒指"):
                assert banned not in ph or banned in str(b.get("others") or ""), (s["shot_no"], ph)


def test_character_detail_fits_a_rainy_alley_fight(segments):
    for s in segments:
        d = character_detail(s)
        assert "点头" not in d and "神态自然放松" not in d, (s["shot_no"], d)
        off = {ln["speaker"] for ln in s["lines"] if ln["kind"] == "offscreen"} - \
              {ln["speaker"] for ln in s["lines"] if ln["kind"] == "onscreen"}
        for name in off:
            assert name not in overall_setting(s).split("；")[0], s["shot_no"]
