"""四格分镜图（T-215）：四格从小镜头挑选的规则、四格文案、出图提示词、视频参考图优先四格图、【画面】S1–S4 标注。"""
import re
from pathlib import Path

import pytest

from core import prompt_tpl
from core.storyboard import (cast_description, panel_tags, pick_beats, storyboard_body, storyboard_panels,
                             storyboard_prompt)
from core.video_prompt import (STORYBOARD_LABEL, STORYBOARD_NAME, FRAME_NAME, assemble_video_prompt, collect_refs,
                               build_upload_plan)

MODEL = {"key": "seedance-2.0-fast", "name": "Seedance", "min_duration": 5, "max_duration": 15,
         "reference_types": ["png", "jpg"], "max_files": 10}


def _beat(start, end, size="中近景", action="甲抬头", expr="", refs=None, camera="正面", move="固定"):
    return {"start": start, "end": end, "shot_size": size, "camera": camera, "move": move, "action": action,
            "expression": expr, "line_refs": refs or []}


def _seg(beats, **extra):
    seg = {"shot_no": 2, "duration": 15, "scene": "雨夜老宅书房，冷灰", "positions": "甲在门口，乙在书桌后",
           "mood": "压抑", "characters": ["甲", "乙"], "props": ["泛黄的信封"], "scene_no": 1,
           "lines": [{"speaker": "甲", "text": "你到底藏了什么？", "kind": "onscreen", "start": 0.5, "end": 2.3}],
           "beats": beats}
    seg.update(extra)
    return seg


BEATS_2 = [_beat(0, 4, "全景", "甲推门，把湿伞靠在门边"), _beat(4, 15, "特写", "乙指尖压住信封边角", "睫毛一颤", [1])]
BEATS_3 = [_beat(0, 3.5, "中景", "甲推门"), _beat(3.5, 8, "特写", "乙指尖压住信封", "睫毛一颤", [1]),
           _beat(8, 15, "近景", "甲逼近一步", "下颌绷紧")]
BEATS_4 = [_beat(0, 4, "全景", "甲推门"), _beat(4, 8, "中近景", "甲盯着桌面", "眼神发冷", [1]),
           _beat(8, 12, "特写", "乙指尖压住信封", "睫毛一颤"), _beat(12, 15, "近景", "乙喉结滚了一下")]
BEATS_5 = [_beat(0, 3, "全景", "甲推门"), _beat(3, 6, "中景", "甲走到桌前"),
           _beat(6, 9, "特写", "乙指尖压住信封", "睫毛一颤，喉结滚动", [1]),
           _beat(9, 12, "近景", "甲把信封抽走", "嘴角一撇"), _beat(12, 15, "中近景", "乙垂下眼", "无")]


# ---------------- 四格挑选规则 ----------------
def test_pick_four_from_four():
    assert pick_beats(BEATS_4) == [0, 1, 2, 3]


def test_pick_two_repeats_by_duration():
    # 第 2 个小镜头 11 秒、第 1 个 4 秒：多出来的两格都给长的那个
    assert pick_beats(BEATS_2) == [0, 1, 1, 1]


def test_pick_three_repeats_longest():
    assert pick_beats(BEATS_3) == [0, 1, 2, 2]


def test_pick_five_keeps_head_tail_and_two_emotion_highs():
    # 首尾必留；中间 3 个里“甲走到桌前”（无表情无台词）落选
    assert pick_beats(BEATS_5) == [0, 2, 3, 4]


def test_pick_none():
    assert pick_beats([]) == [] and storyboard_panels(_seg([])) == [] and storyboard_body(_seg([])) == ""


# ---------------- 四格文案 ----------------
@pytest.mark.parametrize("beats", [BEATS_2, BEATS_3, BEATS_4, BEATS_5])
def test_body_has_four_panels_in_reading_order(beats):
    body = storyboard_body(_seg(beats), "悬疑")
    assert [m for m in re.findall(r"第([一二三四])格（(左上|右上|左下|右下)）", body)] == \
        [("一", "左上"), ("二", "右上"), ("三", "左下"), ("四", "右下")]
    assert body.startswith("【整体设定】场景：雨夜老宅书房，冷灰；站位：甲在门口，乙在书桌后；光影：")
    assert "情绪基调：压抑" in body
    panels = storyboard_panels(_seg(beats))
    assert [p["panel"] for p in panels] == ["S1", "S2", "S3", "S4"]
    # 每格都有景别、人物、动作
    for p in panels:
        assert "人物：" in p["text"] and "动作" in p["text"]


def test_panel_text_fields_and_repeat_split_time():
    panels = storyboard_panels(_seg(BEATS_2))
    assert panels[0]["text"] == "全景，正面；人物：甲；动作：甲推门，把湿伞靠在门边；关键道具：泛黄的信封"   # 静帧不写运镜
    assert "表情：睫毛一颤" in panels[1]["text"]
    # 同一镜头占三格：后两格写“稍后的瞬间”，时间把 4–15 秒三等分
    assert panels[2]["text"].startswith("特写，正面；人物：乙；同一镜头稍后的瞬间，动作延续：")
    assert [(p["start"], p["end"]) for p in panels] == [(0, 4), (4, 7.7), (7.7, 11.3), (11.3, 15)]
    assert [p["beat_index"] for p in panels] == [0, 1, 1, 1]


def test_panel_people_only_those_in_action():
    panels = storyboard_panels(_seg(BEATS_4))
    assert "人物：甲；" in panels[0]["text"] and "人物：乙；" in panels[2]["text"]
    empty = storyboard_panels(_seg([_beat(0, 15, "远景", "雨点砸在窗上")], characters=[]))
    assert "无人物，环境空镜" in empty[0]["text"]


def test_panel_tags_for_each_beat():
    assert panel_tags(_seg(BEATS_4)) == ["S1 左上格", "S2 右上格", "S3 左下格", "S4 右下格"]
    assert panel_tags(_seg(BEATS_2)) == ["S1 左上格", "S2–S4 右上、左下、右下格"]
    assert panel_tags(_seg(BEATS_5)) == ["S1 左上格", "S1 之后的过渡", "S2 右上格", "S3 左下格", "S4 右下格"]


# ---------------- 出图提示词 ----------------
CHARS = [
    {"name": "甲", "gender": "male", "age_group": "青年", "face": "剑眉薄唇，黑色背头",
     "forms": [{"name": "雨夜", "outfit": "黑色风衣，湿透", "scene_nos": [1]},
               {"name": "白日", "outfit": "白衬衫", "scene_nos": [2]}]},
    {"name": "乙", "description": "①女性，青年。②瓜子脸，长发挽起。③体态端庄。④穿搭：墨绿旗袍。⑤特质：沉静。"},
]


def test_cast_uses_face_and_scene_form_or_legacy_description():
    cast = cast_description(_seg(BEATS_4), CHARS)
    assert "甲：男，青年；剑眉薄唇，黑色背头；穿搭：黑色风衣，湿透" in cast
    # 旧数据只有 ①–⑤ 的 description：② 作面部、④ 作穿搭，不带③体态⑤特质
    assert "乙：瓜子脸，长发挽起；穿搭：墨绿旗袍" in cast and "体态端庄" not in cast
    assert "白衬衫" not in cast
    assert "穿搭：白衬衫" in cast_description(_seg(BEATS_4, scene_no=2), CHARS)


def test_storyboard_prompt_fills_template_and_is_safe():
    seg = _seg(BEATS_3)
    p = storyboard_prompt(storyboard_body(seg, "悬疑"), seg, CHARS, "水墨国风", "悬疑")
    assert "2×2 四格分镜图" in p and "【画风】水墨国风" in p
    assert "第一格（左上）" in p and "第四格（右下）" in p
    assert "甲：男，青年；剑眉薄唇" in p and "画面中不出现任何文字" in p
    assert "{" not in p and "}" not in p
    hits = [w for w in ("裸露", "内衣", "走光", "暴露", "血腥", "尸体", "自杀") if w in p]
    assert not hits
    # 文案为空时按段现算；用户手改的文案原样进模板
    assert "第二格（右上）" in storyboard_prompt("", seg, [], "", "")
    assert "我手写的四格" in storyboard_prompt("我手写的四格", seg, [], "", "")
    assert "STORYBOARD_PROMPT" in dir(prompt_tpl)


# ---------------- 视频参考：四格图优先，无四格图回退首帧 ----------------
@pytest.fixture
def static_dir(tmp_path):
    (tmp_path / "images").mkdir()
    for n in ("board.png", "frame.png", "jia.png"):
        (tmp_path / "images" / n).write_bytes(b"png")
    return tmp_path


def test_collect_refs_prefers_storyboard(static_dir):
    chars = [{"name": "甲", "image_path": "images/jia.png"}]
    seg = _seg(BEATS_4, img_path="images/frame.png", storyboard_path="images/board.png")
    refs = collect_refs(seg, chars, [], [], static_dir)
    assert [(r["type"], r["name"], Path(r["path"]).name) for r in refs] == \
        [("分镜参考", STORYBOARD_NAME, "board.png"), ("角色", "甲", "jia.png")]
    # 首帧图不再上传


def test_collect_refs_falls_back_to_frame(static_dir):
    seg = _seg(BEATS_4, img_path="images/frame.png")
    refs = collect_refs(seg, [], [], [], static_dir)
    assert [(r["name"], Path(r["path"]).name) for r in refs] == [(FRAME_NAME, "frame.png")]
    # 四格图文件丢了也回退首帧
    seg["storyboard_path"] = "images/missing.png"
    assert [r["name"] for r in collect_refs(seg, [], [], [], static_dir)] == [FRAME_NAME]


def test_assemble_prompt_labels_panels_when_storyboard_uploaded(static_dir):
    seg = _seg(BEATS_4, storyboard_path="images/board.png",
               video_prompt="开场镜头；[0-4秒]全景，甲推门；[4-8秒]中近景，甲盯着桌面；[8-12秒]特写，乙指尖压住信封；[12-15秒]近景，乙喉结滚了一下")
    plan = build_upload_plan(seg, [], [], [], static_dir, MODEL)
    p = plan["prompt"]
    # R2/F20：四格图在【参考素材】里有 (ref1) 锚点和语义说明，S1–S4 标注才有定义，发送时才会被换成附件芯片
    assert f"[{STORYBOARD_NAME}](ref1)：{STORYBOARD_LABEL}" in p
    assert "左上→右上→左下→右下" in p and "S1–S4" in p and "只约束各时段的构图、站位与光影" in p
    picture = re.search(r"【画面】(.*)", p).group(1)
    assert "[0-4秒 S1 左上格]" in picture and "[4-8秒 S2 右上格]" in picture
    assert "[8-12秒 S3 左下格]" in picture and "[12-15秒 S4 右下格]" in picture
    assert [Path(f).name for f in plan["files"]] == ["board.png"]


def test_assemble_prompt_without_storyboard_keeps_legacy_label():
    seg = _seg(BEATS_4, video_prompt="[0-4秒]全景，甲推门；[4-15秒]特写")
    p = assemble_video_prompt(seg, [{"type": "分镜参考", "name": FRAME_NAME, "path": "/s/frame.png"}])
    assert f"[{FRAME_NAME}](ref1)：本段首帧画面参考（构图与光影以此为准）" in p
    assert "S1" not in p
    # 四格图 + 上一段尾帧同时存在：开场第 0 帧以尾帧为准，四格只约束各时段构图（P9 三套开场依据的优先级）
    both = assemble_video_prompt(seg, [{"type": "关键帧", "name": "上一段尾帧", "path": "/s/tail.png"},
                                       {"type": "分镜参考", "name": STORYBOARD_NAME, "path": "/s/board.png"}])
    assert f"[{STORYBOARD_NAME}](ref2)：{STORYBOARD_LABEL}；开场第 0 帧以上一段尾帧为准" in both
    # 没有任何参考图也不标格
    assert "S1" not in assemble_video_prompt(seg, [])


def test_assemble_prompt_repeat_panels_and_extra_time_spans():
    seg = _seg(BEATS_2, video_prompt="[0-4秒]全景，甲推门；[4-15秒]特写，乙；[15-16秒]多出来的一段")
    p = assemble_video_prompt(seg, [{"type": "分镜参考", "name": STORYBOARD_NAME, "path": "/s/board.png"}])
    assert "[0-4秒 S1 左上格]" in p and "[4-15秒 S2–S4 右上、左下、右下格]" in p
    assert "[15-16秒]多出来的一段" in p


# ---------- 出图“乱七八糟”的修复：画风前置、静帧写法、四格质检与逐格兜底 ----------
def _real_seg():
    return {"scene": "暴雨青石老巷，深夜，冷蓝雨夜", "positions": "铁面具在右侧，沈砚在左侧", "mood": "挑衅",
            "characters": ["铁面具", "沈砚"], "duration": 15,
            "beats": [
                {"start": 0, "end": 4, "shot_size": "中近景", "camera": "铁面具左前方", "move": "缓慢推近",
                 "composition": "铁面具上半身加持刀手臂", "action": "铁面具开口，提刀的手纹丝不动", "expression": "目光森冷"},
                {"start": 4, "end": 8, "shot_size": "特写", "camera": "低机位，贴近水面仰拍", "move": "固定",
                 "composition": "踏水的靴子，积水炸开涟漪", "action": "一脚踩下，积水四溅"},
                {"start": 8, "end": 12, "shot_size": "中近景", "camera": "沈砚右前方", "move": "缓慢推近",
                 "composition": "沈砚抬头侧脸", "action": "他抬起头，雨水顺下颌滴落", "expression": "眼神冷冽"},
                {"start": 12, "end": 15, "shot_size": "空镜", "camera": "低机位", "move": "缓慢横移",
                 "composition": "积水倒映灯火", "action": "水面涟漪散开"}]}


def test_panels_are_still_frames_and_only_list_people_actually_in_frame():
    from core.storyboard import storyboard_panels
    texts = [p["text"] for p in storyboard_panels(_real_seg())]
    assert not any(w in t for t in texts for w in ("缓慢推近", "固定", "横移"))      # 运镜画不出来
    assert "人物：铁面具；" in texts[0] and "沈砚" not in texts[0]
    assert "人物：" not in texts[1]                       # 靴子特写：不再把全段的人都列上
    assert "人物：沈砚；" in texts[2]
    assert "无人物，环境空镜" in texts[3]


def test_storyboard_prompt_puts_style_first_and_drops_conflicting_tone():
    from core.storyboard import storyboard_prompt
    art = "国漫 3D 渲染，细腻材质，电影级光影，空灵缥缈的青白色调，云雾意境，柔和仙光"
    p = storyboard_prompt("", _real_seg(), [], art)
    assert p.startswith("【画风】国漫 3D 渲染")
    assert p.index("【画风】") < p.index("2×2 四格") < p.index("\n【整体设定】") < p.index("【资产设定】") < p.index("【一致性】")
    assert "云雾意境" not in p and "仙光" not in p and "以【整体设定】的环境和光影为准" in p   # 雨夜暗巷不带仙光
    assert "只用上面这一种画风" in p


def test_unedited_old_body_is_refreshed_but_hand_edits_are_kept():
    from core.storyboard import fresh_storyboard_body, storyboard_body
    seg = _real_seg()
    old = storyboard_body(seg, legacy=True)
    assert "缓慢推近" in old                                                  # 旧写法带运镜
    assert fresh_storyboard_body(dict(seg, storyboard_prompt=old)) == storyboard_body(seg)
    edited = old.replace("一脚踩下", "用户改过的动作")
    assert fresh_storyboard_body(dict(seg, storyboard_prompt=edited)) == edited
    assert fresh_storyboard_body(seg) == storyboard_body(seg)


def test_panel_prompt_is_one_frame_with_style_first():
    from core.storyboard import panel_prompt, storyboard_panels
    seg = _real_seg()
    chars = [{"name": "沈砚", "face": "剑眉冷眼", "gender": "male"}, {"name": "铁面具", "face": "覆铁面具"}]
    p = panel_prompt(seg, storyboard_panels(seg)[2], chars, "国漫 3D 渲染")
    assert p.startswith("【画风】国漫 3D 渲染") and "不分格" in p and "他抬起头" in p
    assert "沈砚：" in p and "铁面具：" not in p            # 只带这一格里出现的人的外观


def _png(arr):
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.fromarray(arr).save(buf, format="PNG")
    return buf.getvalue()


def test_grid_check_rejects_single_picture_and_accepts_real_grids():
    import numpy as np
    from core.storyboard_image import compose_grid, looks_like_grid
    rng = np.random.default_rng(7)

    def photo(seed):                      # 平滑的“单幅画面”：低频渐变加少量噪声
        r = np.random.default_rng(seed)
        y, x = np.mgrid[0:400, 0:400]
        base = 120 + 80 * np.sin(x / (40 + seed * 7)) * np.cos(y / (55 + seed * 5))
        img = np.stack([base + r.normal(0, 3, base.shape)] * 3, axis=-1)
        return np.clip(img + np.array([seed * 20, 0, 60 - seed * 15]), 0, 255).astype("uint8")

    single = _png(photo(1))
    assert not looks_like_grid(single)                                        # 单张人像这类跑题图
    grid = compose_grid([_png(photo(i)) for i in range(4)], 1024)
    assert looks_like_grid(grid)                                              # 代码拼的四格
    # 没有黑线、四格直接贴在一起：靠四张图之间的接缝也认得出
    tight = np.vstack([np.hstack([photo(0), photo(3)]), np.hstack([photo(2), photo(1)])])
    assert looks_like_grid(_png(tight))
    assert not looks_like_grid(b"not an image")
    assert rng is not None


def test_compose_grid_layout_and_size():
    import io
    import numpy as np
    from PIL import Image
    from core.storyboard_image import compose_grid
    colors = [(200, 30, 30), (30, 200, 30), (30, 30, 200), (200, 200, 30)]
    tiles = [_png(np.full((300, 500, 3), c, dtype="uint8")) for c in colors]     # 横图会被居中裁成方形
    im = Image.open(io.BytesIO(compose_grid(tiles, 1024)))
    assert im.size == (1024, 1024)
    assert im.getpixel((200, 200)) == colors[0] and im.getpixel((800, 200)) == colors[1]
    assert im.getpixel((200, 800)) == colors[2] and im.getpixel((800, 800)) == colors[3]
    assert im.getpixel((511, 300)) == (0, 0, 0)                                  # 中间的分格线
    with pytest.raises(ValueError):
        compose_grid(tiles[:3])


# ---------- 画面跟资产挂钩：不让出图模型自由设计 ----------
def _assets(tmp_path, with_images=True):
    img = tmp_path / "images"
    img.mkdir(exist_ok=True)
    if with_images:
        for n in ("shen.png", "mask.png", "alley.png"):
            (img / n).write_bytes(b"\x89PNG fake")
    chars = [{"name": "沈砚", "face": "剑眉冷眼，束高马尾", "gender": "male",
              "forms": [{"name": "雨夜负伤", "outfit": "深色短外套", "image_path": "images/shen.png"}]},
             {"name": "铁面具", "face": "覆铁面具，只露双眼",
              "forms": [{"name": "领队", "outfit": "黑色劲装", "image_path": "images/mask.png"}]}]
    scenes = [{"name": "暴雨青石老巷", "description": "狭长的青石板老巷，两侧高墙，檐下挂灯笼，积水反光", "image_path": "images/alley.png"}]
    props = [{"name": "残缺玉牌", "description": "半块青白玉牌，刻一个模糊的封字"}]
    return chars, scenes, props


def test_asset_sheet_binds_characters_scene_props_in_upload_order(tmp_path):
    from core.storyboard import asset_sheet, reference_legend
    chars, scenes, props = _assets(tmp_path)
    seg = dict(_real_seg(), props=["残缺玉牌"])
    sheet = asset_sheet(seg, chars, scenes, props, tmp_path)
    assert [(r["type"], r["name"]) for r in sheet["refs"]] == [("角色", "铁面具"), ("角色", "沈砚"), ("场景", "暴雨青石老巷")] \
        or [(r["type"], r["name"]) for r in sheet["refs"]] == [("角色", "沈砚"), ("角色", "铁面具"), ("场景", "暴雨青石老巷")]
    assert sheet["missing"] == [] and "狭长的青石板老巷" in sheet["scene_text"] and "半块青白玉牌" in sheet["prop_text"]
    assert any("道具「残缺玉牌」还没有参考图" in w for w in sheet["warnings"])
    legend = reference_legend(sheet["refs"])
    assert "图1＝角色" in legend and "图3＝场景「暴雨青石老巷」" in legend and "不另行设计" in legend


def test_asset_sheet_flags_unknown_character_and_missing_images(tmp_path):
    from core.storyboard import asset_sheet
    chars, scenes, props = _assets(tmp_path, with_images=False)
    seg = dict(_real_seg(), characters=["铁面具", "沈砚", "白衣男子"], scene="无名山洞，深夜")
    sheet = asset_sheet(seg, chars, [], props, tmp_path)
    assert sheet["missing"] == ["角色「白衣男子」不在资产页里，先提取或新建这个角色"]
    assert sheet["refs"] == []
    assert any("角色「沈砚」还没有参考图" in w for w in sheet["warnings"])
    assert any("没有绑到任何场景资产" in w for w in sheet["warnings"])


def test_storyboard_prompt_carries_asset_settings_and_legend_only_for_reference_models(tmp_path):
    from core.storyboard import asset_sheet, storyboard_prompt
    chars, scenes, props = _assets(tmp_path)
    seg = dict(_real_seg(), props=["残缺玉牌"])
    sheet = asset_sheet(seg, chars, scenes, props, tmp_path)
    text_only = storyboard_prompt("", seg, chars, "国漫 3D 渲染", sheet=sheet, with_refs=False)
    assert "沈砚：男；剑眉冷眼，束高马尾；穿搭：深色短外套" in text_only
    assert "场景设定：暴雨青石老巷：狭长的青石板老巷" in text_only and "道具设定：残缺玉牌：半块青白玉牌" in text_only
    assert "【参考图】" not in text_only                       # 模型不收图就不提“图1”，免得它乱画
    with_refs = storyboard_prompt("", seg, chars, "国漫 3D 渲染", sheet=sheet, with_refs=True)
    assert "【参考图】图1＝" in with_refs and with_refs.index("【参考图】") < with_refs.index("沈砚：男")


def test_reference_capable_models_and_payload(tmp_path, monkeypatch):
    import asyncio
    from core.providers import fake
    from core.providers import image_provider as IP
    assert IP.supports_reference_images("doubao-seedream-4-0-250828") and IP.supports_reference_images("Doubao-SeedEdit-3.0")
    assert not IP.supports_reference_images("cogview-3-flash") and not IP.supports_reference_images("glm-image")
    assert not IP.supports_reference_images(None)
    f = tmp_path / "a.jpg"
    f.write_bytes(b"abc")
    assert IP._data_uri(str(f)) == "data:image/jpeg;base64,YWJj" and IP._data_uri(str(tmp_path / "none.png")) is None

    sent = []

    class Resp:
        status_code = 200
        content = b"IMG"

        def raise_for_status(self):
            pass

        def json(self):
            return {"data": [{"url": "http://x/y.png"}]}

    class Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, headers=None, json=None):
            sent.append(dict(json))
            return Resp()

        async def get(self, url):
            return Resp()

    monkeypatch.setattr(fake, "enabled", lambda: False)
    monkeypatch.setattr(IP.httpx, "AsyncClient", Client)
    seedream = IP.DoubaoImageProvider("k", "https://ark.example/api/v3", "doubao-seedream-4-0")
    asyncio.run(seedream.generate_image("p", width=1024, height=1024, reference_images=[str(f), str(tmp_path / "none.png")]))
    assert sent[-1]["image"] == ["data:image/jpeg;base64,YWJj"] and sent[-1]["watermark"] is False
    cog = IP.DoubaoImageProvider("k", model="cogview-3-flash")
    asyncio.run(cog.generate_image("p", reference_images=[str(f)]))
    assert "image" not in sent[-1]                             # 不收图的模型不传
