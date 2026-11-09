"""T-214：风格库拆成媒介 + 题材；旧 style_id 兼容映射；风格段落全中文；出图相关文字无敏感词。"""
from core import genre_rhythm as gr
from core.prompt_tpl import REALISTIC_FACE_NOTE
from core.style_library import (
    GENRES, LEGACY_STYLES, MEDIUMS, MEDIUM_GROUPS, build_extract_style_block, build_genre_rhythm, build_style_art_prompt,
    build_style_block, build_video_style_suffix, get_genre, get_medium, is_realistic_style, resolve_style, style_label,
    style_library_payload, style_ref,
)
from test_image_prompt_safety import BANNED

NEW_GENRES = {"家庭伦理", "甜宠虐恋", "现实职场", "重生逆袭"}
OLD_GENRES = {"玄幻", "末世废土", "都市", "仙侠", "悬疑", "轻松搞笑", "古风权谋"}


def _is_chinese(text: str) -> bool:
    """除了 2D/3D/4K/CP 这类通用缩写外没有英文单词。"""
    import re
    stripped = re.sub(r"\b(2D|3D|4K|CP)\b", "", text)
    return not re.search(r"[A-Za-z]{2,}", stripped)


def test_library_shape():
    assert [g["id"] for g in MEDIUM_GROUPS] == ["realistic", "cg3d", "2d"]
    assert {m["id"] for m in MEDIUMS if m["group"] == "2d"} == {"2d_gufeng", "2d_cel", "2d_guoman"}
    assert get_medium("realistic")["realistic"] is True
    assert all(m["realistic"] is False for m in MEDIUMS if m["id"] != "realistic")
    assert {g["name"] for g in GENRES} == OLD_GENRES | NEW_GENRES
    assert len(GENRES) == 11
    # 没有带货 / 海外题材
    assert not any(w in g["name"] or w in g["description"] for g in GENRES for w in ("带货", "海外", "韩漫", "欧美"))
    # 每个题材的节奏键都在节奏表里，倾向词都是中文
    for g in GENRES:
        assert g["genre"] in gr.GENRE_RHYTHM, g["id"]
        for k in ("description", "character_tone", "scene_tone", "art_tone"):
            assert g[k] and _is_chinese(g[k]), (g["id"], k)
    for m in MEDIUMS:
        for k in ("description", "art_style", "video_suffix"):
            assert m[k] and _is_chinese(m[k]), (m["id"], k)


def test_image_bound_text_has_no_sensitive_words():
    """画风词、色调词、视频后缀会直接进出图 / 出视频提示词，不能带会被过滤的词。"""
    texts = [m["art_style"] for m in MEDIUMS] + [m["video_suffix"] for m in MEDIUMS] + [g["art_tone"] for g in GENRES]
    for t in texts:
        hits = [w for w in BANNED if w in t]
        assert not hits, (t, hits)


def test_legacy_style_id_maps_to_cg3d_and_genre():
    for sid, gid in LEGACY_STYLES.items():
        r = resolve_style(style_id=sid)
        assert r["medium"]["id"] == "cg3d" and r["genre"]["id"] == gid and r["custom"] == ""
        # 只有一个字符串时放在 medium 位置也能认出来
        assert resolve_style(medium=sid)["genre"]["id"] == gid
        assert not is_realistic_style(sid)
    assert style_label(style_id="xuanhuan") == "3D 国漫 · 玄幻"
    # 旧项目：style + 自由文本 genre，题材以项目 genre 优先
    r = resolve_style(**style_ref({"style": "dushi", "genre": "婆媳大战"}))
    assert r["medium"]["id"] == "cg3d" and r["genre"]["id"] == "jiating"
    # 旧风格 id 在新字段齐全时不再起作用
    r = resolve_style(**style_ref({"style": "dushi", "genre": "玄幻", "medium": "realistic"}))
    assert r["medium"]["id"] == "realistic" and r["genre"]["id"] == "xuanhuan"


def test_resolve_new_fields_and_custom_text():
    assert get_genre("职场")["id"] == "zhichang" and get_genre("现实职场")["id"] == "zhichang"
    assert get_genre("zhichang")["id"] == "zhichang" and get_genre("都市商战")["id"] == "zhichang"
    assert get_genre("重生")["id"] == "chongsheng" and get_genre("随便写的") is None
    assert get_medium("2d")["id"] == "2d_guoman" and get_medium("none") is None
    r = resolve_style(medium="真人家庭剧")
    assert r["medium"] is None and r["custom"] == "真人家庭剧" and r["genre"]["id"] == "jiating"
    assert is_realistic_style("真人家庭剧") and not is_realistic_style("随便写的")
    assert build_style_block(style_id="某种自定义风格") == "【风格倾向】某种自定义风格"
    assert build_style_art_prompt(style_id="某种自定义风格") == "某种自定义风格"
    assert build_style_block() == "" and build_style_art_prompt() == "" and not is_realistic_style()
    # 请求里显式传的字段优先，空值不覆盖
    assert style_ref({"medium": "cg3d", "genre": "都市"}, medium="2d_cel", genre="") == \
        {"medium": "2d_cel", "genre": "都市", "style_id": None}


def test_style_block_is_chinese_with_medium_and_genre():
    block = build_style_block(medium="realistic", genre="家庭伦理")
    lines = block.split("\n")
    assert lines[0] == "【作品媒介】真人实拍：电影级写实质感，真实皮肤与自然光影，像真人短剧一样可信"
    assert lines[1].startswith("【作品题材】家庭伦理：")
    assert lines[2].startswith("【角色形象倾向】") and "婆婆" in lines[2]
    assert lines[3].startswith("【场景氛围倾向】") and "菜市场" in lines[3]
    assert lines[4].startswith("【画风指令】真人实拍电影级写实质感") and "生活化烟火气" in lines[4]
    assert _is_chinese(block)
    # 旧 style id 同样输出两段
    legacy = build_style_block(style_id="xuanhuan")
    assert "【作品媒介】3D 国漫" in legacy and "【作品题材】玄幻" in legacy and "国漫 3D 渲染" in legacy
    assert _is_chinese(legacy)
    # 只有题材没有媒介：不写画风指令
    only_genre = build_style_block(genre="悬疑")
    assert "【作品题材】悬疑" in only_genre and "【作品媒介】" not in only_genre and "【画风指令】" not in only_genre
    # 真人媒介追加面部真实质感要求；2D 不追加
    assert build_extract_style_block(medium="realistic", genre="职场").endswith(REALISTIC_FACE_NOTE)
    assert REALISTIC_FACE_NOTE not in build_extract_style_block(medium="2d_gufeng", genre="古风")


def test_art_prompt_and_video_suffix_combine_medium_and_genre():
    assert build_style_art_prompt(medium="2d_gufeng", genre="古风") == \
        "2D 国漫古风厚涂画风，工笔线稿勾勒轮廓，水墨晕染与厚重色块结合，东方写意意境，沉稳的东方色调与柔和光影，暖金宫廷色调，华贵烛光氛围，古装华美质感"
    assert build_style_art_prompt(medium="2d_cel") == get_medium("2d_cel")["art_style"]
    assert build_video_style_suffix(medium="realistic", genre="甜宠虐恋") == \
        "真人实拍电影级写实质感，自然写实光影，真实皮肤质感，电影级色调，温馨浪漫的柔光暖调，心动氛围，虐心段落转为冷调雨夜"
    assert build_video_style_suffix(style_id="dushi").startswith("3D 国漫风格")


def test_genre_rhythm_by_medium_and_genre():
    assert "【题材节奏：职场】" in build_genre_rhythm(genre="现实职场", medium="realistic")
    assert "【题材节奏：古风】" in build_genre_rhythm(style_id="gufeng")
    assert "【题材节奏：通用】" in build_genre_rhythm(medium="2d_cel")


def test_payload_for_frontend():
    p = style_library_payload()
    assert [g["id"] for g in p["medium_groups"]] == ["realistic", "cg3d", "2d"]
    assert [m["id"] for m in p["medium_groups"][2]["mediums"]] == ["2d_gufeng", "2d_cel", "2d_guoman"]
    assert len(p["genres"]) == 11 and all(g["description"] for g in p["genres"])
    assert p["default_medium"] == "cg3d" and p["legacy_styles"]["xuanhuan"] == "xuanhuan"


# ---------------- 接口 ----------------
def test_style_library_endpoint_and_project_medium(client, user):
    h = user["headers"]
    data = client.get("/api/config/style-library").json()["data"]
    assert [g["name"] for g in data["medium_groups"]] == ["真人实拍", "3D 国漫", "2D 动漫"]
    assert {g["name"] for g in data["genres"]} >= NEW_GENRES

    r = client.post("/api/projects", json={"name": "媒介题材", "genre": "家庭伦理", "medium": "realistic"}, headers=h)
    pid = r.json()["data"]["id"]
    got = client.get(f"/api/projects/{pid}", headers=h).json()
    assert got["medium"] == "realistic" and got["genre"] == "家庭伦理" and got["style"] is None
    assert client.put(f"/api/projects/{pid}", json={"medium": "2d_cel", "genre": "甜宠虐恋"}, headers=h).status_code == 200
    got = client.get(f"/api/projects/{pid}", headers=h).json()
    assert got["medium"] == "2d_cel" and got["genre"] == "甜宠虐恋"
    assert client.get("/api/projects", headers=h).json()[0]["medium"] == "2d_cel"
    client.delete(f"/api/projects/{pid}", headers=h)
