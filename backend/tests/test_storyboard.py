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
    assert panels[0]["text"] == "全景，正面，固定；人物：甲；动作：甲推门，把湿伞靠在门边；关键道具：泛黄的信封"
    assert "表情：睫毛一颤" in panels[1]["text"]
    # 同一镜头占三格：后两格写“稍后的瞬间”，时间把 4–15 秒三等分
    assert panels[2]["text"].startswith("特写，正面，固定；人物：乙；同一镜头稍后的瞬间，动作延续：")
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
