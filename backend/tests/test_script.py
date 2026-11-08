"""剧本（小说 → 分场剧本）接口与“剧本优先”的下游：替身模式。

- 转剧本走 SSE（progress → done），覆盖旧剧本；
- 场次列表 / 编辑（地点、时间、出场角色、动作、台词逐条增删改）/ 新增 / 删除；
- 有剧本时拆分镜用场次文本（按场次分块），视频段按台词反查场次号；
- 有剧本时一键提取基于剧本。
"""
from conftest import register, sse_done, sse_events
from core.providers.fake import FAKE_NOVEL, FAKE_SCRIPT_SCENES


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
    assert done["data"] == {"count": len(FAKE_SCRIPT_SCENES)}
    assert any(e.get("type") == "progress" and e.get("chars", 0) > 0 for e in sse_events(r))

    scenes = _scenes(client, h, pid)
    assert [s["scene_no"] for s in scenes] == [1, 2]
    first = scenes[0]
    assert first["location"] == "暴雨萧瑟演武场" and first["time"] == "黄昏外"
    assert first["characters"] == ["林风", "赵虎", "苏婉"]
    assert first["dialogues"][3] == {"speaker": "赵虎", "line": "你也配站在这里？"}

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
    r = client.post("/api/shots/split", json={"project_id": pid, "novel_paragraph": "无关的小说段落。"}, headers=h)
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["source"] == "script" and data["format"] == "segment"
    shots = client.get("/api/shots", params={"project_id": pid}, headers=h).json()
    assert [s["scene_no"] for s in shots] == [1, 1, 2]
    # 原文核对用剧本文本：剧本里有的台词不报“原文里找不到”
    assert not [n for n in data["notes"] if "你也配站在这里" in n]


def test_split_without_script_uses_novel(client, project):
    h, pid = project["user"]["headers"], project["id"]
    r = client.post("/api/shots/split", json={"project_id": pid, "novel_paragraph": FAKE_NOVEL}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["data"]["source"] == "novel"
    assert all(s.get("scene_no") is None for s in client.get("/api/shots", params={"project_id": pid}, headers=h).json())
