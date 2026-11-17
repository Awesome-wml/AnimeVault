"""T-228：场景剧情状态 state_note、多视角 views、角色材质规则、剧本 shot_hint。"""
from conftest import sse_done

from api.asset import build_asset_ref_prompt
from core.prompt_tpl import (ASSET_EXTRACT_PROMPT, CHARACTER_EXTRACT_PROMPT, CHARACTER_SHEET_PROMPT,
                             SCENE_EXTRACT_PROMPT, SCENE_REF_PROMPT, SCRIPT_CONVERT_PROMPT)
from core.scene_views import (SINGLE_VIEW_NAME, merge_views_update, normalize_views, scene_doc_fields,
                              scene_views, set_view_image, view_index_of)
from core.script_text import clean_shot_hint, merge_chunk_scenes, scene_text, voiced_of_text

SCENE = {
    "name": "破败山神古庙", "scene_type": "室内", "description": "神像已碎成一地石块的古庙",
    "state_note": "石像碎成石块散落供桌前",
    "views": [
        {"name": "门口视角", "camera": "站在门口朝里，正对供桌", "image_path": "images/v1.png"},
        {"name": "供桌视角", "camera": "贴近供桌朝门口", "image_path": None},
    ],
    "image_path": "images/v1.png",
}


# ---------- 解析 ----------
def test_scene_doc_fields_parse_and_truncate():
    f = scene_doc_fields({"state_note": "碎" * 60, "views": [
        {"name": "正面", "camera": "x" * 50}, "高处俯视", {}, {"name": "", "camera": ""}]})
    assert len(f["state_note"]) == 40
    assert [v["name"] for v in f["views"]] == ["正面", "视角2"]
    assert len(f["views"][0]["camera"]) == 30 and f["views"][1]["camera"] == "高处俯视"
    assert f["image_path"] is None


def test_scene_doc_fields_missing_gives_single_view():
    f = scene_doc_fields({"name": "x", "description": "d"})
    assert f["state_note"] == "" and f["views"] == [{"name": SINGLE_VIEW_NAME, "camera": "", "image_path": None}]


def test_legacy_scene_is_single_view():
    legacy = {"name": "老场景", "image_path": "images/a.png"}
    assert scene_views(legacy) == [{"name": SINGLE_VIEW_NAME, "camera": "", "image_path": "images/a.png"}]
    assert view_index_of(legacy, 3) == 0


def test_set_view_image_and_merge():
    u = set_view_image(SCENE, 1, "images/v2.png")
    assert u["views"][1]["image_path"] == "images/v2.png" and "image_path" not in u
    u = set_view_image(SCENE, 0, "images/n.png")
    assert u["image_path"] == "images/n.png"
    new = merge_views_update(SCENE, [{"name": "改名", "camera": "c"}, {"name": "供桌视角", "camera": "d"}])
    assert [v["image_path"] for v in new] == ["images/v1.png", None]
    assert len(merge_views_update(SCENE, [])) == 1  # 至少保留一个
    assert len(normalize_views([{"name": str(i)} for i in range(10)])) == 6


# ---------- 按视角出图 ----------
def test_scene_prompt_per_view_and_state():
    p0 = build_asset_ref_prompt("scene", SCENE, "水墨", view_index=0)
    p1 = build_asset_ref_prompt("scene", SCENE, "水墨", view_index=1)
    assert "【物件状态】石像碎成石块散落供桌前" in p0
    assert "门口视角：站在门口朝里，正对供桌" in p0 and "供桌视角" not in p0
    assert "供桌视角：贴近供桌朝门口" in p1 and "门口视角" not in p1
    assert "{" not in p0
    # 旧数据：无 state_note / 无机位，不出现多余行
    legacy = build_asset_ref_prompt("scene", {"name": "老场景", "description": "空旷大厅"}, "")
    # 新 scene_ref 模板的固定文案里本身含“布局与物件状态保持一致”，只断言两个占位行不出现
    assert "【物件状态】" not in legacy and "【机位视角】" not in legacy and "空旷大厅" in legacy


# ---------- 模板 ----------
def test_scene_extract_templates_have_state_and_views():
    for tpl in (SCENE_EXTRACT_PROMPT, ASSET_EXTRACT_PROMPT):
        assert '"state_note"' in tpl and '"views"' in tpl and '"camera"' in tpl
        assert "不超过 40 字" in tpl and "不超过 30 字" in tpl
        tpl.format(novel_text="x", style_block="")
    assert "{scene_state_line}" in SCENE_REF_PROMPT


def test_character_rules_require_material_and_state():
    for tpl in (CHARACTER_EXTRACT_PROMPT, ASSET_EXTRACT_PROMPT):
        assert "材质+状态" in tpl and "补丁" in tpl and "皮肤真实肌理" in tpl
    assert "统一站姿" in CHARACTER_SHEET_PROMPT and "影棚柔光" in CHARACTER_SHEET_PROMPT


# ---------- shot_hint ----------
def test_shot_hint_prompt_and_parse():
    assert '"shot_hint"' in SCRIPT_CONVERT_PROMPT and "不超过 20 字" in SCRIPT_CONVERT_PROMPT
    assert clean_shot_hint("中景，" + "字" * 40) == ("中景，" + "字" * 40)[:20]
    assert clean_shot_hint(None) == "" and clean_shot_hint({"a": 1}) == ""
    scenes = merge_chunk_scenes([[{"location": "甲", "time": "夜"}]])  # 缺省不报错
    assert "shot_hint" not in scenes[0]
    text = scene_text({"scene_no": 1, "location": "甲", "shot_hint": "近景，信封", "dialogues": [
        {"speaker": "旁白", "line": "你好。", "kind": "narration"}]})
    assert "镜头提示（不配音，仅参考）：近景，信封" in text
    assert voiced_of_text(text) == "你好。"


# ---------- 接口 ----------
def test_extract_all_stores_state_note_views_and_generates_per_view(client, project):
    h = project["user"]["headers"]
    pid = project["id"]
    assert sse_done(client.post("/api/assets/extract-all", json={"project_id": pid, "novel_text": "林风站在演武场。"}, headers=h))
    scenes = client.get("/api/scenes", params={"project_id": pid}, headers=h).json()
    s = scenes[0]
    assert s["state_note"] == "兵器架倾倒、地面积水" and [v["name"] for v in s["views"]] == ["正面视角", "高台视角"]
    for i in (0, 1):
        r = client.post("/api/assets/generate", json={"asset_type": "scene", "asset_id": s["id"], "view_index": i}, headers=h)
        assert r.status_code == 200, r.text
        assert r.json()["data"]["view_index"] == i
    s = client.get("/api/scenes", params={"project_id": pid}, headers=h).json()[0]
    assert all(v["image_path"] for v in s["views"]) and s["image_path"] == s["views"][0]["image_path"]
    # 编辑视角：沿用原图
    r = client.put(f"/api/scenes/{s['id']}", json={"state_note": "改过", "views": [
        {"name": "新名", "camera": "c"}, {"name": "高台视角", "camera": "d"}, {"name": "第三视角", "camera": "e"}]}, headers=h)
    assert r.status_code == 200
    s2 = client.get("/api/scenes", params={"project_id": pid}, headers=h).json()[0]
    assert s2["state_note"] == "改过" and len(s2["views"]) == 3
    assert s2["views"][0]["image_path"] == s["views"][0]["image_path"] and s2["views"][2]["image_path"] is None


def test_script_convert_stores_shot_hint(client, project):
    h = project["user"]["headers"]
    pid = project["id"]
    sse_done(client.post("/api/scripts/convert", json={"project_id": pid, "novel_text": "林风站在演武场。"}, headers=h))
    scripts = client.get("/api/scripts/list", params={"project_id": pid}, headers=h).json()["data"]["scripts"]
    assert scripts[0]["shot_hint"] == "全景到中景，暴雨演武场"
    assert scripts[1]["shot_hint"] == ""  # 缺省不报错
    sid = scripts[0]["id"]
    assert client.put(f"/api/scripts/{sid}", json={"shot_hint": "特" * 30}, headers=h).status_code == 200
    again = client.get("/api/scripts/list", params={"project_id": pid}, headers=h).json()["data"]["scripts"]
    assert len(again[0]["shot_hint"]) == 20
