"""R5：语速 / 时长口径只在 core/pacing.py 定义一次，其余地方只读。不连库、不连模型。"""
import asyncio
import re
from pathlib import Path

from core import pacing, prompt_tpl, shot_timing, video_models
from core.prompt_registry import _CONSTRAINT_FILE, _SYSTEM_FILE, _load, build_messages
from core.video_models import get_video_model, segment_budget, segment_params

CORE = Path(__file__).resolve().parents[1] / "core"


def test_chars_per_second_defined_once():
    """`CHARS_PER_SECOND = 数字` 在 backend/core 下只允许出现在 pacing.py。"""
    hits = [p.name for p in CORE.rglob("*.py")
            if re.search(r"^CHARS_PER_SECOND\s*=\s*[\d.]+", p.read_text(encoding="utf-8"), re.M)]
    assert hits == ["pacing.py"]
    assert shot_timing.CHARS_PER_SECOND is pacing.CHARS_PER_SECOND
    assert prompt_tpl.CHARS_PER_SECOND is pacing.CHARS_PER_SECOND
    assert video_models.CHARS_PER_SECOND is pacing.CHARS_PER_SECOND
    assert shot_timing.SPEECH_MARGIN == pacing.SPEECH_MARGIN_SECONDS == video_models.CONTENT_MARGIN_HIGH


def test_default_value_is_compromise_pending_measurement():
    """未真机测语速前取折中 5.0（4.5 旧剧本口径 ～ 6.0 拆段口径），MEASURED 标 False 提醒待测。"""
    assert pacing.CHARS_PER_SECOND == 5.0 and pacing.MEASURED["chars_per_second"] is False
    assert pacing.FIRST_FRAME_HOLD_SECONDS == 1.0 and pacing.MEASURED["first_frame_hold_seconds"] is False
    assert pacing.fmt_number(5.0) == "5" and pacing.fmt_number(4.5) == "4.5"
    assert pacing.chars_for_seconds(13) == 65 and pacing.seconds_for_chars(65) == 13


def test_templates_do_not_hardcode_speed():
    """注册表与 legacy 模板里不再写死“每秒 6 字”“每秒 4.5 字”，统一用 {chars_per_second} 占位。"""
    raw = Path(_CONSTRAINT_FILE).read_text(encoding="utf-8") + Path(_SYSTEM_FILE).read_text(encoding="utf-8")
    assert not re.search(r"每秒 ?\d+(\.\d+)? ?字", raw)
    for key in ("split_shots", "split_shots_script"):
        assert "{chars_per_second}" in _load(_CONSTRAINT_FILE)["prompts"][key]["default"]
        assert "chars_per_second" in _load(_SYSTEM_FILE)["prompts"][key]["placeholders"]
    for tpl in (prompt_tpl.SHOT_SPLIT_PROMPT, prompt_tpl.SHOT_SPLIT_SCRIPT_PROMPT):
        assert "每秒 {chars_per_second} 字" in tpl and "4.5" not in tpl


def test_segment_params_and_script_budget_share_speed():
    """拆分镜装段字数与剧本篇幅预算用同一个语速：拆段 chars_low/high = 8/10 秒 × 语速（多段续接口径，每段台词不塞满）。"""
    fast = get_video_model()
    params = segment_params(fast)
    cps = pacing.CHARS_PER_SECOND
    assert params["chars_per_second"] == pacing.fmt_number(cps)
    assert params["chars_low"] == int(8 * cps) and params["chars_high"] == int(10 * cps)
    # 每段只装 10 秒台词：300 秒目标 → 台词 200 秒 → 约 20 段 × 15 秒 ≈ 300 秒（不按 300 秒全说话多出段数）
    speech = pacing.speech_seconds_for_target(300, fast["max_duration"])
    assert speech == 200
    assert f"不超过 {int(speech * cps)} 个字" in prompt_tpl.script_length_rule(1000, 300, fast["max_duration"])
    budget = segment_budget("一" * int(speech * cps), fast)
    assert budget["segment_count_hint"] * fast["max_duration"] == 300
    user = build_messages("split_shots", novel_paragraph="x", chunk_note="", **params,
                          **segment_budget("一" * 100, fast))[-1]["content"]
    assert f"中文按每秒 {params['chars_per_second']} 字计，约 {params['chars_low']} 到 {params['chars_high']} 个字" in user


def test_config_endpoint_exposes_pacing():
    from api.config import get_video_models
    data = asyncio.run(get_video_models()).data
    assert data["pacing"]["chars_per_second"] == pacing.CHARS_PER_SECOND
    assert data["pacing"]["speech_margin_seconds"] == pacing.SPEECH_MARGIN_SECONDS
    assert data["pacing"]["measured"] == pacing.MEASURED and data["models"]
