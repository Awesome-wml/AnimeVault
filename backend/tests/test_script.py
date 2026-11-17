"""剧本（小说 → 分场剧本）接口与“剧本优先”的下游：替身模式。

- 转剧本走 SSE（progress → done），覆盖旧剧本；
- 场次列表 / 编辑（地点、时间、出场角色、动作、台词逐条增删改）/ 新增 / 删除；
- 有剧本时拆分镜用场次文本（按场次分块），视频段按台词反查场次号；
- 有剧本时一键提取基于剧本。
"""
from conftest import register, sse_done, sse_events
from api.script import build_script_prompts, resolve_person, resolve_target_seconds
from api.shot import build_segments
from core import shot_timing as ST
from core.prompt_tpl import SCRIPT_CONVERT_PROMPT, SCRIPT_PERSON_RULES, SHOT_SPLIT_SCRIPT_PROMPT, script_length_rule
from core.providers.fake import FAKE_NOVEL, FAKE_SCRIPT_SCENES
from core.script_text import (chunk_scenes, clean_dialogues, halve_scene_chunk, merge_chunk_scenes, normalize_kind,
                              scripts_to_text, voiced_of_text, voiced_text)
from core.video_models import get_video_model


def _text(messages):
    return "\n".join(m["content"] for m in messages)


def _convert(client, h, pid):
    r = client.post("/api/scripts/convert", json={"project_id": pid, "novel_text": FAKE_NOVEL}, headers=h)
    return r


def _scenes(client, h, pid):
    r = client.get("/api/scripts/list", params={"project_id": pid}, headers=h)
    assert r.status_code == 200, r.text
    return r.json()["data"]["scripts"]


def test_convert_script_sse_and_overwrite(client, project):
    h, pid = project["user"]["headers"], project["id"]
    r = _convert(client, h, pid)
    done = sse_done(r)
    assert done["data"] == {"count": len(FAKE_SCRIPT_SCENES), "chunks": 1}
    assert any(e.get("type") == "progress" and e.get("chars", 0) > 0 for e in sse_events(r))

    scenes = _scenes(client, h, pid)
    assert [s["scene_no"] for s in scenes] == [1, 2]
    first = scenes[0]
    assert first["location"] == "暴雨萧瑟演武场" and first["time"] == "黄昏外"
    assert first["characters"] == ["林风", "赵虎", "苏婉"]
    assert first["dialogues"][3] == {"speaker": "赵虎", "line": "你也配站在这里？", "kind": "onscreen"}
    assert first["dialogues"][5] == {"speaker": "林风", "line": "再忍一忍。", "kind": "inner"}
    assert first["dialogues"][0]["kind"] == "narration"

    # 再转一次：覆盖而不是追加
    sse_done(_convert(client, h, pid))
    assert len(_scenes(client, h, pid)) == 2


def test_convert_requires_key_and_project(client, user, keyed_user):
    h = user["headers"]
    pid = client.post("/api/projects", json={"name": "无密钥"}, headers=h).json()["data"]["id"]
    r = client.post("/api/scripts/convert", json={"project_id": pid, "novel_text": "一段小说"}, headers=h)
    assert r.status_code == 400 and "密钥" in r.json()["detail"]
    r = client.post("/api/scripts/convert", json={"project_id": "bad", "novel_text": "x"},
                    headers=keyed_user["headers"])
    assert r.status_code == 400


def test_edit_scene_dialogues_create_delete(client, project):
    h, pid = project["user"]["headers"], project["id"]
    sse_done(_convert(client, h, pid))
    scene = _scenes(client, h, pid)[1]

    # 改地点/时间/出场/动作，台词：改第 1 条、删第 2 条、末尾新增一条；空台词被丢弃
    dialogues = [dict(d) for d in scene["dialogues"]]
    dialogues[0]["line"] = "赵虎挥掌而来。"
    del dialogues[1]
    dialogues.append({"speaker": "赵虎", "line": "你给我等着！"})
    dialogues.append({"speaker": "", "line": "   "})
    r = client.put(f"/api/scripts/{scene['id']}", json={
        "location": "演武场东侧", "time": "夜外", "characters": ["林风", "赵虎", "围观族人"],
        "action": "雨更大了。", "dialogues": dialogues,
    }, headers=h)
    assert r.status_code == 200, r.text
    got = next(s for s in _scenes(client, h, pid) if s["id"] == scene["id"])
    assert got["location"] == "演武场东侧" and got["time"] == "夜外" and got["action"] == "雨更大了。"
    assert got["characters"] == ["林风", "赵虎", "围观族人"]
    assert [d["line"] for d in got["dialogues"]] == ["赵虎挥掌而来。", "三个月后的族比，我等你。", "你给我等着！"]

    # 新增一场：场次号接着编
    r = client.post("/api/scripts", json={"project_id": pid, "location": "林家祠堂",
                                           "dialogues": [{"speaker": "旁白", "line": "夜深了。"}]}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["data"]["scene_no"] == 3
    # 删除一场
    assert client.delete(f"/api/scripts/{scene['id']}", headers=h).status_code == 200
    assert [s["location"] for s in _scenes(client, h, pid)] == ["暴雨萧瑟演武场", "林家祠堂"]
    assert client.delete(f"/api/scripts/{scene['id']}", headers=h).status_code == 404


def test_scenes_are_private(client, project):
    h, pid = project["user"]["headers"], project["id"]
    sse_done(_convert(client, h, pid))
    scene = _scenes(client, h, pid)[0]
    other = register(client, "other")["headers"]
    assert client.get("/api/scripts/list", params={"project_id": pid}, headers=other).json()["data"]["scripts"] == []
    assert client.put(f"/api/scripts/{scene['id']}", json={"location": "x"}, headers=other).status_code == 404
    assert client.delete(f"/api/scripts/{scene['id']}", headers=other).status_code == 404


def test_split_shots_uses_script_scenes(client, project):
    """有剧本时拆分镜用场次文本：返回 source=script，段按台词反查到场次号（1、1、2）。"""
    h, pid = project["user"]["headers"], project["id"]
    sse_done(client.post("/api/assets/extract-all", json={"project_id": pid, "novel_text": FAKE_NOVEL}, headers=h))
    sse_done(_convert(client, h, pid))
    # 传入的小说段落故意写成别的内容：有剧本时不该用它
    # fb4ef9a 起拆分镜接口是 SSE（进度 + done），结果在 done 事件的 data 里
    r = client.post("/api/shots/split", json={"project_id": pid, "novel_paragraph": "无关的小说段落。"}, headers=h)
    data = sse_done(r)["data"]
    assert data["source"] == "script" and data["format"] == "segment"
    shots = client.get("/api/shots", params={"project_id": pid}, headers=h).json()
    assert [s["scene_no"] for s in shots] == [1, 1, 2]
    # 原文核对用剧本文本：剧本里有的台词不报“原文里找不到”
    assert not [n for n in data["notes"] if "你也配站在这里" in n]


def test_split_without_script_uses_novel(client, project):
    h, pid = project["user"]["headers"], project["id"]
    r = client.post("/api/shots/split", json={"project_id": pid, "novel_paragraph": FAKE_NOVEL}, headers=h)
    assert sse_done(r)["data"]["source"] == "novel"
    assert all(s.get("scene_no") is None for s in client.get("/api/shots", params={"project_id": pid}, headers=h).json())


# ---------------- T-206：人称 / 篇幅 / 分块转剧本 / kind / 场次号 ----------------
def test_script_prompt_injects_person_and_length():
    novel = "第一段。" * 50
    [(chunk, render)] = build_script_prompts("script_convert", None, novel, style_block="【作品风格】都市",
                                             genre_rhythm="【题材节奏：都市】", person="first",
                                             target_seconds=120, chunk_chars=4000)
    prompt = _text(render(None))
    assert SCRIPT_PERSON_RULES["first"] in prompt
    from core.pacing import CHARS_PER_SECOND   # 剧本篇幅预算与拆分镜共用同一语速（R5）
    assert "本集目标时长约 120 秒" in prompt and f"不超过 {int(120 * CHARS_PER_SECOND)} 个字" in prompt
    assert "【题材节奏：都市】" in prompt and "【作品风格】都市" in prompt
    assert "【分块说明】" not in prompt and "{" not in render(None)[1]["content"].split("【小说原文】")[0]
    # 不给目标时长：按原文三成
    [(_, render)] = build_script_prompts("script_convert", None, novel, style_block="", genre_rhythm="",
                                         person="keep", target_seconds=0, chunk_chars=4000)
    assert script_length_rule(len(novel)) in _text(render(None))
    assert SCRIPT_PERSON_RULES["keep"] in _text(render(None))


def test_script_prompt_chunks_long_novel():
    para = "暴雨压在演武场上，青石板被砸得白茫茫一片。" * 10
    novel = "\n".join([para] * 12)
    parts = build_script_prompts("script_convert", None, novel, style_block="", genre_rhythm="", person="third",
                                 target_seconds=300, chunk_chars=1000)
    assert len(parts) >= 3 and all(len(c) <= 1000 for c, _ in parts)
    first = _text(parts[0][1](None))
    second = _text(parts[1][1]({"location": "演武场", "time": "夜，外", "characters": ["林风"]}))
    assert f"这是第 1 块" in first and "开头钩子只在第 1 块要求" not in first
    assert "这是第 2 块" in second and "上一块最后一场：地点“演武场”" in second
    # 目标时长按块字数分摊（每块约 300 * 块长 / 全文长 秒）
    assert "本集目标时长约" in second


def test_resolve_person_and_target():
    assert resolve_person(None, {}) == "keep"
    assert resolve_person("FIRST", {"script_person": "third"}) == "first"
    assert resolve_person(None, {"script_person": "third"}) == "third"
    assert resolve_person("bogus", {}) == "keep"
    assert resolve_target_seconds(None, {"script_target_seconds": 90}) == 90
    assert resolve_target_seconds(0, {"script_target_seconds": 90}) == 0
    assert resolve_target_seconds(None, {}) == 0


def test_merge_chunk_scenes_renumbers_and_joins_boundary():
    a = [{"scene_no": 1, "location": "包厢", "time": "夜，内", "characters": ["陆川"],
          "dialogues": [{"speaker": "陆川", "line": "一辆代步车而已。", "kind": "onscreen"}], "action": "举杯"},
         {"scene_no": 2, "location": "走廊", "time": "夜，内", "characters": ["陆川"],
          "dialogues": [{"speaker": "旁白", "line": "他走了出去。"}], "action": "推门"}]
    b = [{"scene_no": 1, "location": "走廊", "time": "夜，内", "characters": ["赵一帆"],
          "dialogues": [{"speaker": "赵一帆", "line": "停手吧。"}], "action": "追出来"},
         {"scene_no": 2, "location": "路口", "time": "深夜，外", "characters": ["陆川"],
          "dialogues": [{"speaker": "陆川", "line": "活该。", "kind": "inner"}]}]
    merged = merge_chunk_scenes([a, b])
    assert [s["scene_no"] for s in merged] == [1, 2, 3]
    assert [s["location"] for s in merged] == ["包厢", "走廊", "路口"]
    hall = merged[1]
    assert [d["line"] for d in hall["dialogues"]] == ["他走了出去。", "停手吧。"]
    assert hall["characters"] == ["陆川", "赵一帆"] and hall["action"] == "推门；追出来"
    assert hall["dialogues"][1]["kind"] == "onscreen" and hall["dialogues"][0]["kind"] == "narration"


def test_kind_fallback():
    assert normalize_kind("旁白", "inner") == ("旁白", "narration")
    assert normalize_kind("陆川", "narration") == ("旁白", "narration")
    assert normalize_kind("陆川", "") == ("陆川", "onscreen")
    assert normalize_kind("陆川", "OFFSCREEN") == ("陆川", "offscreen")
    assert normalize_kind("", None) == ("旁白", "narration")
    out = clean_dialogues([{"speaker": "陆川", "line": " 我不甘心。 ", "kind": "inner"}, {"speaker": "x", "line": "  "}])
    assert out == [{"speaker": "陆川", "line": "我不甘心。", "kind": "inner"}]


def test_kind_kept_through_edit_and_list(client, project):
    h, pid = project["user"]["headers"], project["id"]
    sse_done(_convert(client, h, pid))
    scene = _scenes(client, h, pid)[0]
    r = client.put(f"/api/scripts/{scene['id']}", json={"dialogues": [
        {"speaker": "林风", "line": "迟早让他后悔。", "kind": "inner"},
        {"speaker": "旁白", "line": "雨更大了。", "kind": "onscreen"},
        {"speaker": "赵虎", "line": "站住！"},
        {"speaker": "苏婉", "line": "小心！", "kind": "offscreen"},
    ]}, headers=h)
    assert r.status_code == 200, r.text
    got = next(s for s in _scenes(client, h, pid) if s["id"] == scene["id"])
    assert [d["kind"] for d in got["dialogues"]] == ["inner", "narration", "onscreen", "offscreen"]


def test_script_text_voiced_and_chunks():
    text = scripts_to_text(FAKE_SCRIPT_SCENES)
    assert "林风（心声）：再忍一忍。" in text
    assert "动作/环境（不配音）：" in text and "节拍（不配音）：" in text
    voiced = voiced_text(FAKE_SCRIPT_SCENES)
    assert "再忍一忍。" in voiced and "节拍" not in voiced and "动作" not in voiced and "【场次" not in voiced
    assert voiced_of_text(text).split("\n") == voiced.split("\n")
    # 单场超长：按台词条切开，每片都带场头
    long_scene = dict(FAKE_SCRIPT_SCENES[0], dialogues=FAKE_SCRIPT_SCENES[0]["dialogues"] * 6)
    chunks = chunk_scenes([long_scene], 400)
    assert len(chunks) > 1 and all(c.startswith("【场次1】") for c in chunks)
    halves = halve_scene_chunk(chunks[0])
    assert len(halves) == 2 and halves[1].startswith("【场次1】") and "台词：" in halves[1]


def test_build_segments_keeps_model_scene_no():
    model = get_video_model(None)
    raw = [{"scene_no": 2, "scene": "演武场", "lines": [{"speaker": "林风", "text": "三个月后的族比，我等你。", "kind": "onscreen"}],
            "beats": []},
           {"scene_no": "3", "scene": "演武场", "lines": [{"speaker": "旁白", "text": "夜深了。", "kind": "narration"}],
            "beats": []}]
    fields, _ = build_segments(raw, model, set(), set())
    assert [f["scene_no"] for f in fields] == [2, 3]
    # 场景名相同但场次不同：不会被当成同一场景重新装段
    assert ST.scene_key(raw[0]) != ST.scene_key(raw[1])


def test_project_script_settings(client, project):
    h, pid = project["user"]["headers"], project["id"]
    r = client.put(f"/api/projects/{pid}", json={"script_person": "first", "script_target_seconds": 120}, headers=h)
    assert r.status_code == 200, r.text
    got = client.get(f"/api/projects/{pid}", headers=h).json()
    assert got["script_person"] == "first" and got["script_target_seconds"] == 120
    # 0 = 清空目标时长
    client.put(f"/api/projects/{pid}", json={"script_target_seconds": 0}, headers=h)
    assert client.get(f"/api/projects/{pid}", headers=h).json()["script_target_seconds"] is None
    assert client.put(f"/api/projects/{pid}", json={"script_person": "second"}, headers=h).status_code == 400


def test_convert_long_novel_in_chunks(client, project):
    """长文分块转剧本：SSE 进度带第几块/共几块，合并后场次从 1 连续编号。"""
    h, pid = project["user"]["headers"], project["id"]
    novel = "\n\n".join([FAKE_NOVEL] * 20)   # 约 5400 字，SCRIPT_CHUNK_CHARS=4000 → 2 块
    r = client.post("/api/scripts/convert", json={"project_id": pid, "novel_text": novel, "person": "third",
                                                   "target_seconds": 120}, headers=h)
    done = sse_done(r)
    assert done["data"]["chunks"] == 2
    progress = [e for e in sse_events(r) if e.get("type") == "progress" and e.get("chunk")]
    assert {e["chunk"] for e in progress} == {1, 2} and all(e["total"] == 2 for e in progress)
    scenes = _scenes(client, h, pid)
    # 替身每块返回同样两场；块交界处“演武场中央”与“暴雨萧瑟演武场”地点不同，不合并
    assert [s["scene_no"] for s in scenes] == [1, 2, 3, 4]
    assert done["data"]["count"] == 4


def test_shot_split_script_template_contract():
    """剧本版拆分镜模板：内置剧本格式说明，要求回填 scene_no，占位与小说版一致。"""
    assert "剧本格式说明" in SHOT_SPLIT_SCRIPT_PROMPT and "scene_no" in SHOT_SPLIT_SCRIPT_PROMPT


def test_long_output_advice_table(client):
    """拆分镜不稳的模型（glm-4.x-flash）在模型列表里带推荐提示；稳定的不带。前端只读这个字段。"""
    from core.providers import model_caps as MC
    zhipu = "https://open.bigmodel.cn/api/paas/v4"
    assert MC.long_output_advice(zhipu, "glm-4.7-flash")["recommended"] == "glm-5.3-flashx"
    assert MC.long_output_advice(zhipu, "glm-5.3-flashx") is None
    assert MC.long_output_advice("https://api.deepseek.com/v1", "glm-4.7-flash") is None
    r = client.post("/api/models", json={"name": "E2E 长输出", "provider": "zhipu",
                                         "models": "glm-4.7-flash\nglm-5.3-flashx", "api_keys": ""})
    mid = r.json()["id"]
    try:
        row = next(m for m in client.get("/api/models").json()["data"] if m["_id"] == mid)
        assert set(row["long_output_advice"]) == {"glm-4.7-flash"}
        assert "建议拆分镜用 glm-5.3-flashx" in row["long_output_advice"]["glm-4.7-flash"]["message"]
    finally:
        client.delete(f"/api/models/{mid}")
