"""角色形态（core/character_forms.py）：多形态提取解析、按 scene_no 选图、旧数据兼容；
三视图提示词按形态填（api/asset.build_asset_ref_prompt）；真人类风格追加面部要求。"""
from core.character_forms import (SINGLE_FORM_NAME, character_doc_fields, character_forms, form_for_scene,
                                  form_index_of, merge_forms_update, normalize_forms, set_form_image)
from core.prompt_tpl import (ASSET_EXTRACT_PROMPT, CHARACTER_EXTRACT_PROMPT, CHARACTER_SHEET_PROMPT,
                             REALISTIC_FACE_NOTE, VOICE_ATTRIBUTES)
from core.style_library import build_extract_style_block, is_realistic_style

EXTRACTED = {
    "name": "周桂芳",
    "face": "58岁女性，圆脸微胖，颧骨较高，眼尾下垂有岁月纹路，肤色偏黄带晒斑，短发烫着小卷。",
    "forms": [
        {"name": "上门索财形态", "outfit": "枣红色碎花棉绸上衣，黑色宽松长裤，深灰色布鞋，腋下夹黑色旧挎包。", "scene_nos": [1, 2, 5]},
        {"name": "被拆穿失态形态", "outfit": "头发散乱，同一件枣红上衣扣子崩开一颗，手里攥着存折。", "scene_nos": "3，4、6"},
    ],
    "voice": "58岁女性，泼辣",
    "importance": "main", "gender": "female", "age_group": "暮年", "trait": "泼辣",
}


# ---------------- 多形态提取解析 ----------------
def test_parse_multi_form_character():
    f = character_doc_fields(EXTRACTED)
    assert f["face"].startswith("58岁女性")
    assert [x["name"] for x in f["forms"]] == ["上门索财形态", "被拆穿失态形态"]
    assert f["forms"][0]["scene_nos"] == [1, 2, 5]
    # 场次写成中文逗号/顿号字符串也能解析
    assert f["forms"][1]["scene_nos"] == [3, 4, 6]
    assert f["voice"] == "58岁女性，泼辣"
    # 旧字段 description = 面部 + 第一形态穿搭，image_path 为空
    assert f["description"].startswith(f["face"]) and "枣红色碎花棉绸上衣" in f["description"]
    assert f["image_path"] is None


def test_parse_legacy_description_only():
    """旧模板 / 自建提示词只给 description：face 取 description，单形态，穿搭取 description。"""
    f = character_doc_fields({"name": "甲", "description": "三十岁男子，黑衬衫。"})
    assert f["face"] == "三十岁男子，黑衬衫。"
    assert f["forms"] == [{"name": SINGLE_FORM_NAME, "outfit": "三十岁男子，黑衬衫。", "scene_nos": [], "image_path": None}]
    assert f["voice"] is None


def test_normalize_forms_drops_empty_and_names_unnamed():
    forms = normalize_forms([{"outfit": "蓝衣", "scene_nos": [2, 2, 0, "x"]}, {}, "红衣"])
    assert [f["name"] for f in forms] == ["形态1", "形态2"]
    assert forms[0]["scene_nos"] == [2] and forms[1]["outfit"] == "红衣"


# ---------------- 按 scene_no 选图 ----------------
CHAR = {
    "name": "周桂芳", "face": "圆脸微胖",
    "forms": [
        {"name": "索财形态", "outfit": "枣红上衣", "scene_nos": [1, 2, 5], "image_path": "images/f1.png"},
        {"name": "失态形态", "outfit": "扣子崩开", "scene_nos": [3, 4], "image_path": "images/f2.png"},
    ],
    "image_path": "images/f1.png",
}


def test_form_for_scene_picks_matching_form():
    form, warn = form_for_scene(CHAR, 3)
    assert form["name"] == "失态形态" and form["image_path"] == "images/f2.png" and warn is None
    form, warn = form_for_scene(CHAR, "5")
    assert form["name"] == "索财形态" and warn is None


def test_form_for_scene_falls_back_to_first_with_warning():
    form, warn = form_for_scene(CHAR, 9)
    assert form["name"] == "索财形态" and "第 9 场" in warn and "索财形态" in warn
    form, warn = form_for_scene(CHAR, None)
    assert form["name"] == "索财形态" and "本段" in warn


def test_single_form_never_warns():
    legacy = {"name": "甲", "description": "黑衬衫", "image_path": "images/a.png"}
    form, warn = form_for_scene(legacy, 7)
    assert form["image_path"] == "images/a.png" and warn is None


# ---------------- 旧数据兼容 ----------------
def test_legacy_character_is_single_form():
    legacy = {"name": "甲", "description": "三十岁男子，黑衬衫。", "image_path": "images/a.png"}
    forms = character_forms(legacy)
    assert forms == [{"name": SINGLE_FORM_NAME, "outfit": "三十岁男子，黑衬衫。", "scene_nos": [],
                      "image_path": "images/a.png"}]
    assert form_index_of(legacy, 5) == 0


def test_first_form_mirrors_image_path():
    """有 forms 但只写了旧字段 image_path（旧代码写回）：第一形态取它。"""
    c = {"forms": [{"name": "A", "outfit": "x"}, {"name": "B", "outfit": "y"}], "image_path": "images/old.png"}
    assert character_forms(c)[0]["image_path"] == "images/old.png"
    assert character_forms(c)[1]["image_path"] is None


def test_set_form_image_syncs_root_only_for_first():
    update = set_form_image(CHAR, 1, "images/new2.png")
    assert update["forms"][1]["image_path"] == "images/new2.png" and "image_path" not in update
    update = set_form_image(CHAR, 0, "images/new1.png")
    assert update["image_path"] == "images/new1.png" and update["forms"][0]["image_path"] == "images/new1.png"
    # 越界下标回到第一形态
    assert set_form_image(CHAR, 9, "images/z.png")["image_path"] == "images/z.png"


def test_merge_forms_update_keeps_images_by_index():
    new = merge_forms_update(CHAR, [{"name": "改名了", "outfit": "枣红上衣", "scene_nos": [1, 2]},
                                   {"name": "失态形态", "outfit": "扣子崩开", "scene_nos": [3, 4, 6]},
                                   {"name": "新形态", "outfit": "白衣"}])
    assert [f["image_path"] for f in new] == ["images/f1.png", "images/f2.png", None]
    assert new[0]["name"] == "改名了" and new[1]["scene_nos"] == [3, 4, 6]


# ---------------- 三视图：每个形态一张，face + 该形态穿搭 ----------------
def test_sheet_prompt_uses_face_and_form_outfit():
    from api.asset import build_asset_ref_prompt
    p1 = build_asset_ref_prompt("character", CHAR, "水墨", form_index=0)
    p2 = build_asset_ref_prompt("character", CHAR, "水墨", form_index=1)
    # 档案页模板（05658af）写法：角色为{名}，{性别}，{年龄段}；{face}；{形态名}：{outfit}。face 与本形态 outfit 仍按形态注入
    assert "圆脸微胖" in p1 and "索财形态：枣红上衣" in p1 and "扣子崩开" not in p1
    assert "失态形态：扣子崩开" in p2 and "枣红上衣" not in p2
    assert "{" not in p1 and "}" not in p1
    # 旧数据：单形态，穿搭取 description
    legacy = {"name": "甲", "description": "三十岁男子，黑衬衫。", "gender": "male", "age_group": "青年"}
    p = build_asset_ref_prompt("character", legacy, "")
    assert "角色为甲，男性，青年（约18到30岁）；三十岁男子，黑衬衫。；单形态：三十岁男子，黑衬衫。" in p
    # 多形态：穿搭只取本形态（旧的 {character_description} 自建模板已随 DB 提示词下线）
    assert "索财形态：" not in p2


def test_extract_templates_share_form_rules():
    for tpl in (CHARACTER_EXTRACT_PROMPT, ASSET_EXTRACT_PROMPT):
        assert '"face"' in tpl and '"forms"' in tpl and '"scene_nos"' in tpl and '"voice"' in tpl
        assert "【声音属性库】" in tpl and "泼辣" in tpl and "电子机械音" in tpl
        assert "{{" not in tpl.format(novel_text="x", style_block="")
    assert all(v for v in VOICE_ATTRIBUTES.values())
    assert "{character_face}" in CHARACTER_SHEET_PROMPT and "{character_outfit}" in CHARACTER_SHEET_PROMPT


# ---------------- 真人类风格：face 要求真实肤质 ----------------
def test_realistic_style_adds_face_note():
    assert is_realistic_style("realistic_family") and is_realistic_style("真人家庭剧") and not is_realistic_style("dushi")
    assert REALISTIC_FACE_NOTE in build_extract_style_block("真人家庭剧")
    assert REALISTIC_FACE_NOTE not in build_extract_style_block("dushi")
    assert build_extract_style_block("dushi").startswith("【作品媒介】3D 国漫")
    # 新字段：媒介定义里的 realistic 字段说了算
    assert is_realistic_style("realistic") and not is_realistic_style("2d_cel")
    assert REALISTIC_FACE_NOTE in build_extract_style_block(medium="realistic", genre="家庭伦理")
