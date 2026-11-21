"""提示词管理接口（只读展示 core/prompts/*.json）与注册表约束内容。不连库。"""
import json

from api import prompt as prompt_api
from core import prompt_registry as R


def test_list_reflects_registry_files():
    sys_keys = set(R._load(R._SYSTEM_FILE)["prompts"])
    out = prompt_api.list_prompts()
    assert out["read_only"] is True and "core/prompts/" in out["note"]
    base = [r for r in out["data"] if ":" not in r["_id"]]
    assert {r["type"] for r in base} == sys_keys
    for r in base:
        assert r["is_builtin"] and r["read_only"] and r["category"] == "通用"
    split = next(r for r in base if r["type"] == "split_shots")
    assert split["content"] == R.get_entry("split_shots")["constraint"]
    assert [r["type"] for r in prompt_api.list_prompts(type="novel")["data"] if ":" not in r["_id"]] == ["novel"]


def test_no_write_routes_and_no_db_sync():
    methods = {m for r in prompt_api.router.routes for m in r.methods}
    assert methods == {"GET"}
    import core.llm_factory as F
    assert not hasattr(F, "resolve_prompt")


def test_split_shots_keeps_shot_size_constraint():
    for key in ("split_shots", "split_shots_script"):
        text = "\n".join(m["content"] for m in R.build_messages(
            key, novel_paragraph="x", chunk_note="", novel_seconds=60, content_low=8, content_high=12,
            segment_count_hint=5, chars_low=30, chars_high=50))
        assert "景别以特写、近景、中近景为主" in text
        assert "禁止连续 3 个小镜头同一景别" in text


def test_constraint_text_has_no_repeated_numbered_rules():
    """R6：scene_extract / asset_extract 曾把规则 6、7 原样写了两遍；注册表任何一段约束里编号规则不得重复。"""
    import re
    doc = R._load(R._CONSTRAINT_FILE)["prompts"]
    for key, entry in doc.items():
        texts = [entry.get("default") or ""]
        for v in (entry.get("variants") or {}).values():
            texts.append(v.get("text", "") if isinstance(v, dict) else (v or ""))
        for text in texts:
            rules = [ln.strip() for ln in text.split("\n") if re.match(r"^\s*\d+\.\s", ln)]
            dup = {r for r in rules if rules.count(r) > 1}
            assert not dup, (key, sorted(dup)[0][:40])


def test_fill_does_not_touch_braces_inside_user_text():
    """用户小说里恰好出现 {person_rule}、{abc} 这类花括号，不能被当成占位符替换或删掉（单次扫描）。"""
    from core.prompt_registry import _fill
    novel = "他写下{person_rule}和{abc}，还有{Name1}。"
    out = _fill("原文：{novel_paragraph}\n人称：{person_rule}\n{missing}", {"novel_paragraph": novel, "person_rule": "第一人称"})
    assert novel in out
    assert "人称：第一人称" in out
    assert "{missing}" not in out
