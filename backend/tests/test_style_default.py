"""T-265：媒介缺省（真人实拍）、参考图写实约束、风格不一致提示、视频【风格】行必有。"""
from api.asset import build_asset_ref_prompt
from core.style_library import (FALLBACK_MEDIUM, REALISTIC_CONSISTENCY_NOTE, build_ref_style_guard, build_style_art_prompt,
                                build_video_style_line, medium_key, resolve_style, style_mismatch_warnings, style_ref)
from core.video_prompt import build_upload_plan
from tests.test_image_prompt_safety import BANNED

CHAR = {"name": "萧尘", "gender": "male", "age_group": "青年", "face": "剑眉星目", "forms": [{"name": "常服", "outfit": "青色长衫"}]}


def test_empty_project_defaults_to_realistic():
    ref = style_ref({"genre": "玄幻"})  # 测试2 那种：medium/style 全空，只有题材
    assert ref["medium"] == FALLBACK_MEDIUM == "realistic"
    assert resolve_style(**ref)["medium"]["id"] == "realistic"
    assert medium_key(**ref) == "realistic"
    assert "真人实拍" in build_style_art_prompt(**ref)
    # 旧 style 有值按旧映射（3D 国漫），已选的 medium 不被覆盖
    assert style_ref({"style": "dushi"})["medium"] is None
    assert medium_key(**style_ref({"style": "dushi"})) == "cg3d"
    assert style_ref({"medium": "2d_cel"})["medium"] == "2d_cel"


def test_ref_prompts_have_realism_guard_when_realistic():
    ref = style_ref({})
    art = build_style_art_prompt(**ref)
    for t, a in (("character", CHAR), ("prop", {"name": "玉佩", "description": "古玉"}), ("scene", {"name": "演武场", "description": "空地"})):
        p = build_asset_ref_prompt(t, a, art, style_guard=build_ref_style_guard(t, **ref))
        assert "非动漫非插画非线稿" in p and "{style_guard}" not in p
        assert not [w for w in BANNED if w in p]
    # 非真人媒介不加
    cg = style_ref({"medium": "cg3d"})
    assert build_ref_style_guard("character", **cg) == ""
    assert "非动漫" not in build_asset_ref_prompt("character", CHAR, "x", style_guard="")


def test_guard_has_no_banned_words():
    for t in ("character", "prop", "scene"):
        g = build_ref_style_guard(t, medium="realistic")
        assert g and not [w for w in BANNED if w in g]
    assert not [w for w in BANNED if w in REALISTIC_CONSISTENCY_NOTE]


def test_video_style_line_always_present():
    line = build_video_style_line()  # 什么都没传也有
    assert "真人实拍" in line and REALISTIC_CONSISTENCY_NOTE in line
    assert REALISTIC_CONSISTENCY_NOTE not in build_video_style_line(medium="cg3d")
    assert "3D 国漫" in build_video_style_line(medium="cg3d")
    seg = {"scene_no": 1, "duration": 8, "lines": [{"speaker": "A", "text": "你好"}], "beats": [{"text": "A说话"}]}
    plan = build_upload_plan(seg, [], [], [], __import__("pathlib").Path("/nonexistent"), {"reference_types": ["png"], "max_files": 5})
    assert "【风格】" in plan["prompt"] and REALISTIC_CONSISTENCY_NOTE in plan["prompt"]


def test_style_mismatch_warnings():
    docs = [{"_id": "c1", "style_medium": "2d_cel"}, {"_id": "s1", "style_medium": "realistic"}, {"_id": "p1"}]
    refs = [{"type": "角色", "name": "萧尘", "asset_id": "c1"}, {"type": "场景", "name": "殿", "asset_id": "s1"},
            {"type": "道具", "name": "剑", "asset_id": "p1"}]
    w = style_mismatch_warnings(refs, docs, "realistic")
    assert len(w) == 1 and "萧尘" in w[0] and "日系赛璐璐" in w[0] and "建议重新出图" in w[0]
    assert style_mismatch_warnings(refs, docs, "") == []
    assert style_mismatch_warnings(refs, [{"_id": "c1", "style_medium": "realistic"}], "realistic") == []
