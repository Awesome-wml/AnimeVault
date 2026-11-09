"""资产-分镜绑定（core/asset_binding.py）与参考图编号（core/video_prompt.py）的单元测试。

关键约束：只有一套【@图片N】编号逻辑——build_upload_plan 产出的 files（上传顺序）与 prompt 里的
图N / 【@图片N】出自同一个 refs 列表，N 就是 files 里的第 N 个。
"""
import re
from pathlib import Path

import pytest

from core.asset_binding import collect_bindings
from core.script_text import chunk_scenes, locate_scene_no, scripts_to_text
from core.video_prompt import build_upload_plan

MODEL = {"reference_types": ["png", "jpg", "jpeg", "webp"], "max_files": 9}

CHARS = [
    {"_id": "c1", "name": "林风", "importance": "main", "image_path": "images/linfeng.png"},
    {"_id": "c2", "name": "赵虎", "importance": "support", "image_path": "images/zhaohu.png"},
    {"_id": "c3", "name": "苏婉", "importance": "support", "image_path": None},  # 没有图
]
SCENES = [
    {"_id": "s1", "name": "暴雨萧瑟演武场", "description": "青石板演武场，四周回廊", "image_path": "images/yanwu.png"},
    {"_id": "s2", "name": "林家幽静书房", "description": "书房里一张长案", "image_path": "images/shufang.png"},
]
PROPS = [
    {"_id": "p1", "name": "青铜古戒", "image_path": "images/ring.png"},
    {"_id": "p2", "name": "油纸伞", "image_path": "images/umbrella.png"},
]


@pytest.fixture
def static_dir(tmp_path):
    (tmp_path / "images").mkdir()
    for name in ("linfeng", "zhaohu", "yanwu", "shufang", "ring", "umbrella", "frame"):
        (tmp_path / "images" / f"{name}.png").write_bytes(b"\x89PNG")
    return tmp_path


def _segment(**kw):
    seg = {
        "shot_no": 2, "duration": 15, "scene": "暴雨萧瑟演武场，黄昏暴雨",
        "characters": ["赵虎", "林风"], "props": ["青铜古戒"],
        "video_prompt": "赵虎俯视林风；林风左手青铜古戒泛起微光；苏婉在廊下",
        "lines": [{"speaker": "赵虎", "text": "你也配站在这里？", "kind": "onscreen", "start": 0, "end": 2.4},
                  {"speaker": "旁白", "text": "林风没有抬头。", "kind": "narration", "start": 2.4, "end": 5}],
    }
    seg.update(kw)
    return seg


# ---------------- collect_bindings ----------------
def test_bindings_order_and_labels():
    b = collect_bindings(_segment(), CHARS, SCENES, PROPS)
    assert [(x["asset_type"], x["name"], x["label"]) for x in b] == [
        ("character", "林风", "主角"), ("character", "赵虎", "配角"),
        ("scene", "暴雨萧瑟演武场", "场景"), ("prop", "青铜古戒", "道具"),
    ]
    assert b[0]["asset_id"] == "c1" and b[0]["img"] == "images/linfeng.png"


def test_structured_fields_win_over_text():
    """视频段有 characters / props 字段时按字段选：文本里出现的苏婉、油纸伞不绑定。"""
    seg = _segment(video_prompt="苏婉撑着油纸伞看着赵虎和林风")
    names = [x["name"] for x in collect_bindings(seg, CHARS, SCENES, PROPS)]
    assert "苏婉" not in names and "油纸伞" not in names


def test_legacy_shot_matches_by_text():
    shot = {"text": "苏婉撑着油纸伞", "prompt": "书房里，苏婉看向窗外"}
    names = [x["name"] for x in collect_bindings(shot, CHARS, SCENES, PROPS)]
    assert names == ["苏婉", "林家幽静书房", "油纸伞"]


def test_scene_location_from_script():
    """场次地点（剧本 location）指向书房时绑定书房，即使正文没写场景全名。"""
    shot = {"text": "林风翻开旧账本", "characters": ["林风"]}
    assert [x["name"] for x in collect_bindings(shot, CHARS, SCENES, PROPS)] == ["林风"]
    b = collect_bindings(shot, CHARS, SCENES, PROPS, scene_location="林家书房")
    assert [x["name"] for x in b] == ["林风", "林家幽静书房"]


FORM_CHARS = [
    {"_id": "c1", "name": "林风", "importance": "main", "face": "清瘦长脸", "image_path": "images/linfeng.png",
     "forms": [{"name": "扫地形态", "outfit": "青布短打", "scene_nos": [1], "image_path": "images/linfeng.png"},
               {"name": "立威形态", "outfit": "衣袖挽起", "scene_nos": [2], "image_path": "images/linfeng2.png"}]},
    {"_id": "c2", "name": "赵虎", "importance": "support", "image_path": "images/zhaohu.png"},  # 旧数据：单形态
]


def test_character_image_picked_by_scene_no():
    """按段所属场次选形态的图：第 2 场用“立威形态”；旧数据角色照旧用 image_path，不提示。"""
    shot = {"text": "林风一招逼退赵虎", "characters": ["林风", "赵虎"], "scene_no": 2}
    b = collect_bindings(shot, FORM_CHARS, SCENES, PROPS)
    assert [(x["name"], x["img"], x.get("form"), x.get("warning")) for x in b] == [
        ("林风", "images/linfeng2.png", "立威形态", None),
        ("赵虎", "images/zhaohu.png", "单形态", None),
    ]
    b = collect_bindings(shot, FORM_CHARS, SCENES, PROPS, scene_no=1)
    assert b[0]["img"] == "images/linfeng.png" and b[0]["form"] == "扫地形态"


def test_character_form_falls_back_with_warning(static_dir):
    """没有对应场次的形态：用第一形态并在 warnings 里提示；提示词里的图说明带形态名。"""
    (static_dir / "images" / "linfeng2.png").write_bytes(b"\x89PNG")
    seg = _segment(characters=["林风", "赵虎"], scene_no=7)
    plan = build_upload_plan(seg, FORM_CHARS, SCENES, PROPS, static_dir, MODEL)
    assert [Path(f).name for f in plan["files"]][:2] == ["linfeng.png", "zhaohu.png"]
    assert plan["warnings"] == ["林风 没有对应第 7 场的形态，已用第一形态「扫地形态」的参考图"]
    assert "图1：角色林风（出场，扫地形态，五官服装以此为准）" in plan["prompt"]
    assert "图2：角色赵虎（主讲，五官服装以此为准）" in plan["prompt"]
    seg = _segment(characters=["林风", "赵虎"], scene_no=2)
    plan = build_upload_plan(seg, FORM_CHARS, SCENES, PROPS, static_dir, MODEL)
    assert [Path(f).name for f in plan["files"]][0] == "linfeng2.png" and plan["warnings"] == []


def test_rhetoric_scene_word_ignored():
    """“与书房的安静形成反差”这类修辞里的场景词不算当前场景。"""
    shot = {"text": "演武场上喧闹嘈杂，与书房的安静形成反差", "characters": ["林风"]}
    names = [x["name"] for x in collect_bindings(shot, CHARS, SCENES, PROPS)]
    assert "林家幽静书房" not in names


# ---------------- build_upload_plan：编号 = 上传顺序 ----------------
def _numbering(prompt: str) -> dict:
    """【参考素材】里的 图N：... → {N: 说明}"""
    m = re.search(r"【参考素材】(.*)", prompt)
    return {int(n): desc for n, desc in re.findall(r"图(\d+)：([^；\n]*)", m.group(1))}


def test_upload_files_and_prompt_numbering_agree(static_dir):
    seg = _segment(img_path="images/frame.png")
    plan = build_upload_plan(seg, CHARS, SCENES, PROPS, static_dir, MODEL)
    files = [Path(f).name for f in plan["files"]]
    # 段首画面 → 角色（按资产顺序）→ 场景 → 道具；苏婉没有图不占编号
    assert files == ["frame.png", "linfeng.png", "zhaohu.png", "yanwu.png", "ring.png"]
    numbering = _numbering(plan["prompt"])
    assert len(numbering) == len(files)
    names = ["", "林风", "赵虎", "暴雨萧瑟演武场", "青铜古戒"]
    for i, name in enumerate(names, start=1):
        assert name in numbering[i] if name else "首帧" in numbering[i]
    # 画面里内联的【@图片N】：N 指向的文件就是该名字的参考图
    picture = re.search(r"【画面】(.*)", plan["prompt"]).group(1)
    for name, n in re.findall(r"(林风|赵虎|青铜古戒|暴雨萧瑟演武场)【@图片(\d+)】", picture):
        assert names[int(n) - 1] == name
    assert "赵虎【@图片3】" in picture and "青铜古戒【@图片5】" in picture
    assert "苏婉【@图片" not in picture


def test_max_files_truncates_both(static_dir):
    """模型最多收 3 张：上传和提示词编号一起截断，不会出现图4。"""
    plan = build_upload_plan(_segment(img_path="images/frame.png"), CHARS, SCENES, PROPS, static_dir,
                             {**MODEL, "max_files": 3})
    assert len(plan["files"]) == 3
    assert sorted(_numbering(plan["prompt"])) == [1, 2, 3]
    assert "【@图片4】" not in plan["prompt"] and "【@图片5】" not in plan["prompt"]


def test_missing_file_does_not_shift_numbering(static_dir):
    (static_dir / "images" / "zhaohu.png").unlink()
    plan = build_upload_plan(_segment(), CHARS, SCENES, PROPS, static_dir, MODEL)
    assert [Path(f).name for f in plan["files"]] == ["linfeng.png", "yanwu.png", "ring.png"]
    assert "青铜古戒【@图片3】" in plan["prompt"]
    assert plan["warnings"] == ["赵虎 有画内台词但没有参考图"]


def test_extra_refs_numbered_after_assets(static_dir):
    tail = static_dir / "images" / "umbrella.png"
    plan = build_upload_plan(_segment(), CHARS, SCENES, PROPS, static_dir, MODEL,
                             extra_refs=[{"type": "关键帧", "name": "上一段尾帧", "path": str(tail)}])
    assert Path(plan["files"][-1]).name == "umbrella.png"
    assert "上一段尾帧" in _numbering(plan["prompt"])[len(plan["files"])]


def test_legacy_shot_sends_raw_prompt(static_dir):
    shot = {"shot_no": 1, "text": "赵虎冷笑", "video_prompt": "原样发送的提示词"}
    plan = build_upload_plan(shot, CHARS, SCENES, PROPS, static_dir, MODEL)
    assert plan["prompt"] == "原样发送的提示词"
    assert [Path(f).name for f in plan["files"]] == ["zhaohu.png"]


def test_automation_filter_keeps_plan_order(static_dir):
    """豆包自动化 _task_files 再按扩展名 / 上限过滤一次，顺序与数量不变。"""
    from core.doubao_automation import DoubaoVideoGenerator
    plan = build_upload_plan(_segment(img_path="images/frame.png"), CHARS, SCENES, PROPS, static_dir, MODEL)
    task = {"assets": plan["files"], **MODEL}
    assert DoubaoVideoGenerator._task_files(task) == plan["files"]


# ---------------- 剧本场次分块 / 场次反查 ----------------
SCRIPTS = [
    {"scene_no": 1, "location": "演武场", "dialogues": [{"speaker": "旁白", "line": "暴雨压在林家演武场上。"},
                                                     {"speaker": "赵虎", "line": "你也配站在这里？"}]},
    {"scene_no": 2, "location": "书房", "dialogues": [{"speaker": "林风", "line": "三个月后的族比，我等你。"}]},
    {"scene_no": 3, "location": "祠堂", "action": "香火缭绕。" * 40, "dialogues": []},
]


def test_scripts_to_text_format():
    text = scripts_to_text(SCRIPTS[:1])
    assert text.startswith("【场次1】\n地点：演武场")
    assert "台词：\n旁白：暴雨压在林家演武场上。\n赵虎：你也配站在这里？" in text


def test_chunk_scenes_only_cuts_between_scenes():
    chunks = chunk_scenes(SCRIPTS, 200)
    # 场次 1+2 合在一块，场次 3（只有超长动作、没有台词）单独一块
    assert chunks[0].count("【场次") == 2 and "【场次3】" not in chunks[0]
    assert "".join(chunks).count("【场次") == 3
    # 足够大时一块装下
    assert len(chunk_scenes(SCRIPTS, 5000)) == 1


def test_locate_scene_no():
    assert locate_scene_no([{"text": "你也配站在这里？"}], SCRIPTS) == 1
    assert locate_scene_no([{"text": "三个月后的族比，我等你"}], SCRIPTS) == 2
    assert locate_scene_no([{"text": "原文里没有的话呀呀呀"}], SCRIPTS) is None
