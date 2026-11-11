"""主流程（替身模式）：小说 → 提取资产 → 风格 → 资产出图 → 拆分镜 → 画面 → 视频 → 配音 → 字幕 → 剪映 → 剧集

按文件内顺序执行，后一步依赖前一步写入的数据（共享 flow 状态）。
"""
import json
import os
import threading
from pathlib import Path

import httpx
import pytest

from conftest import register, sse_done, sse_events

NOVEL = """暴雨压在林家演武场上。林风攥着扫帚站在场边。
赵虎踩着积水走过来，冷笑一声：“你也配站在这里？”
林风左手的青铜古戒忽然发烫。苏婉撑着油纸伞站在廊下。"""


@pytest.fixture(scope="module")
def flow(client):
    u = register(client, "flow")
    h = u["headers"]
    assert client.put("/api/auth/config", json={"doubao_api_key": "e2e-fake-key"}, headers=h).status_code == 200
    r = client.post("/api/projects", json={"name": "暴雨演武场", "genre": "玄幻"}, headers=h)
    return {"h": h, "token": u["token"], "pid": r.json()["data"]["id"]}


def _static(client, rel: str) -> httpx.Response:
    r = client.get(f"/static/{rel}")
    assert r.status_code == 200, f"/static/{rel} -> {r.status_code}"
    return r


def _ep1_novel(client, h, pid) -> str:
    """小说正文按集存放：读第一集的正文"""
    return client.get("/api/video-set/list", params={"project_id": pid}, headers=h).json()[0]["novel_content"]


def test_novel_generate_sse(client, flow):
    """AI 写小说：SSE 流式返回 chunk，结束后写回作品"""
    params = {"project_id": flow["pid"], "genre": "玄幻", "style": "xuanhuan", "outline": "少年受辱后觉醒",
              "protagonist": "林风", "target_words": 1000, "token": flow["token"]}
    chunks, done = [], False
    with client.stream("GET", "/api/novel/generate", params=params) as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        for line in r.iter_lines():
            if not line.startswith("data: "):
                continue
            evt = json.loads(line[6:])
            assert evt["type"] != "error", evt
            if evt["type"] == "chunk":
                chunks.append(evt["content"])
            elif evt["type"] == "done":
                done = True
    assert done and len(chunks) > 1
    proj = client.get(f"/api/projects/{flow['pid']}", headers=flow["h"]).json()
    # 小说正文归到所属集（默认第一集），项目级不再存正文
    ep1 = client.get("/api/video-set/list", params={"project_id": flow["pid"]}, headers=flow["h"]).json()[0]
    assert ep1["novel_content"].startswith("暴雨演武场")
    assert proj["style"] == "xuanhuan" and proj["genre"] == "玄幻"


def test_novel_save_and_polish(client, flow):
    h, pid = flow["h"], flow["pid"]
    # 长篇正文走 JSON 请求体（放 URL 会 431）
    long_text = NOVEL * 40
    r = client.post("/api/novel/save", json={"project_id": pid, "content": long_text}, headers=h)
    assert r.status_code == 200, r.text
    assert _ep1_novel(client, h, pid) == long_text
    # 旧的查询参数方式仍兼容（短文）
    r = client.post("/api/novel/save", params={"project_id": pid, "content": NOVEL}, headers=h)
    assert r.status_code == 200
    assert _ep1_novel(client, h, pid) == NOVEL

    r = client.post("/api/novel/polish", json={"project_id": pid, "text": NOVEL, "person": "third"}, headers=h)
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["text"].startswith("（润色稿）") and data["source_length"] == len(NOVEL)
    # 润色只返回结果，不覆盖原文
    assert _ep1_novel(client, h, pid) == NOVEL


def test_extract_all_assets(client, flow):
    h, pid = flow["h"], flow["pid"]
    r = client.post("/api/assets/extract-all", json={"project_id": pid, "novel_text": NOVEL}, headers=h)
    # SSE：过程中推 progress（已收字符数），最后 done 带统计
    assert sse_done(r)["data"] == {"characters": 3, "props": 1, "scenes": 1}
    assert any(e.get("type") == "progress" for e in sse_events(r))

    chars = client.get("/api/characters", params={"project_id": pid}, headers=h).json()
    assert {c["name"] for c in chars} == {"林风", "赵虎", "苏婉"}
    main = next(c for c in chars if c["name"] == "林风")
    assert main["importance"] == "main" and main["gender"] == "male" and main["age_group"] == "少年"
    assert [s["name"] for s in client.get("/api/scenes", params={"project_id": pid}, headers=h).json()] == ["暴雨萧瑟演武场"]
    assert [p["name"] for p in client.get("/api/props", params={"project_id": pid}, headers=h).json()] == ["青铜古戒"]


def _char(client, h, pid, cid):
    return next(c for c in client.get("/api/characters", params={"project_id": pid}, headers=h).json() if c["id"] == cid)


def test_character_forms_api(client, project):
    """角色形态：提取落库 face / forms / voice；旧数据单形态；按形态出图与上传；改形态名和场次；
    有剧本拆分镜时按段所属场次选该形态的图。"""
    h, pid = project["user"]["headers"], project["id"]
    sse_done(client.post("/api/assets/extract-all", json={"project_id": pid, "novel_text": NOVEL}, headers=h))
    chars = {c["name"]: c for c in client.get("/api/characters", params={"project_id": pid}, headers=h).json()}
    lf = chars["林风"]
    assert lf["face"].startswith("十七岁少年") and lf["voice"] == "17岁男性，清亮"
    assert [(f["name"], f["scene_nos"], f["image_path"]) for f in lf["forms"]] == \
        [("场边扫地形态", [1], None), ("雨中立威形态", [2], None)]
    assert lf["description"].startswith(lf["face"])
    # 旧格式（只有 description）：单形态，穿搭取 description
    sw = chars["苏婉"]
    assert sw["forms"] == [{"name": "单形态", "outfit": sw["description"], "scene_nos": [], "image_path": None}]

    # 第二形态出图：只写该形态，旧字段 image_path 仍为空；第一形态上传时同步 image_path
    r = client.post("/api/assets/generate", json={"asset_type": "character", "asset_id": lf["id"], "form_index": 1}, headers=h)
    assert r.status_code == 200, r.text
    img2 = r.json()["data"]["img_path"]
    assert r.json()["data"]["form_index"] == 1
    got = _char(client, h, pid, lf["id"])
    assert got["forms"][1]["image_path"] == img2 and got["forms"][0]["image_path"] is None and got["image_path"] is None
    png = (Path(__file__).parent / "fixtures" / "placeholder.png").read_bytes()
    r = client.post("/api/assets/upload", params={"asset_type": "character", "asset_id": lf["id"], "form_index": 0},
                    files={"file": ("p.png", png, "image/png")}, headers=h)
    assert r.status_code == 200, r.text
    img1 = r.json()["data"]["img_path"]
    got = _char(client, h, pid, lf["id"])
    assert got["forms"][0]["image_path"] == img1 == got["image_path"] and got["forms"][1]["image_path"] == img2

    # 改形态名与场次：不带 image_path 也沿用原图；形态不能清空
    forms = [{"name": "扫地", "outfit": got["forms"][0]["outfit"], "scene_nos": [1, 3]},
             {"name": "立威", "outfit": got["forms"][1]["outfit"], "scene_nos": [2]}]
    assert client.put(f"/api/characters/{lf['id']}", json={"forms": forms, "voice": "17岁男性，干净"}, headers=h).status_code == 200
    got = _char(client, h, pid, lf["id"])
    assert [(f["name"], f["scene_nos"], f["image_path"]) for f in got["forms"]] == [("扫地", [1, 3], img1), ("立威", [2], img2)]
    assert got["voice"] == "17岁男性，干净"
    assert client.put(f"/api/characters/{lf['id']}", json={"forms": []}, headers=h).status_code == 400

    # 有剧本时拆分镜：段按场次绑定，第 2 场的段用“立威”的图，第 1 场用“扫地”的图
    sse_done(client.post("/api/scripts/convert", json={"project_id": pid, "novel_text": NOVEL}, headers=h))
    assert client.post("/api/shots/split", json={"project_id": pid, "novel_paragraph": NOVEL}, headers=h).status_code == 200
    shots = client.get("/api/shots", params={"project_id": pid}, headers=h).json()
    by_scene = {}
    for s in shots:
        for a in s["assets"]:
            if a["name"] == "林风":
                by_scene.setdefault(s["scene_no"], set()).add((a["form"], a["img"]))
    assert by_scene == {1: {("扫地", img1)}, 2: {("立威", img2)}}
    # 每段都找到了对应场次的形态：没有“没有对应…形态”的提示（没参考图的说话人提示与形态无关）
    assert not [w for s in shots for w in (s.get("prompt_warnings") or []) if "形态" in w]


@pytest.mark.parametrize("kind,key", [("characters", "characters"), ("scenes", "scenes"), ("props", "props")])
def test_extract_single_kind(client, keyed_user, kind, key):
    """单类提取（角色 / 场景 / 道具页的“AI 提取”）"""
    h = keyed_user["headers"]
    pid = client.post("/api/projects", json={"name": "单类提取"}, headers=h).json()["data"]["id"]
    r = client.post(f"/api/{kind}/extract", json={"project_id": pid, "novel_text": NOVEL, "style": "xuanhuan"}, headers=h)
    assert r.status_code == 200, r.text
    assert len(client.get(f"/api/{kind}", params={"project_id": pid}, headers=h).json()) >= 1


def test_style_update(client, flow):
    h, pid = flow["h"], flow["pid"]
    assert client.put(f"/api/projects/{pid}", json={"genre": "玄幻", "style": "xuanhuan"}, headers=h).status_code == 200
    assert client.get(f"/api/projects/{pid}", headers=h).json()["style"] == "xuanhuan"


@pytest.mark.parametrize("asset_type,path", [("character", "characters"), ("scene", "scenes"), ("prop", "props")])
def test_asset_reference_image(client, flow, asset_type, path):
    h, pid = flow["h"], flow["pid"]
    item = client.get(f"/api/{path}", params={"project_id": pid}, headers=h).json()[0]
    r = client.post("/api/assets/generate", json={"asset_type": asset_type, "asset_id": item["id"]}, headers=h)
    assert r.status_code == 200, r.text
    img = r.json()["data"]["img_path"]
    assert img.startswith("images/") and img.endswith(".png")
    assert _static(client, img).content[:8] == b"\x89PNG\r\n\x1a\n"
    again = next(i for i in client.get(f"/api/{path}", params={"project_id": pid}, headers=h).json() if i["id"] == item["id"])
    assert again["image_path"] == img


def test_asset_upload_image(client, flow):
    h, pid = flow["h"], flow["pid"]
    prop = client.get("/api/props", params={"project_id": pid}, headers=h).json()[0]
    png = (Path(__file__).parent / "fixtures" / "placeholder.png").read_bytes()
    r = client.post("/api/assets/upload", params={"asset_type": "prop", "asset_id": prop["id"]},
                    files={"file": ("p.png", png, "image/png")}, headers=h)
    assert r.status_code == 200, r.text
    r = client.post("/api/assets/upload", params={"asset_type": "prop", "asset_id": prop["id"]},
                    files={"file": ("p.txt", b"hello", "text/plain")}, headers=h)
    assert r.status_code == 400 and r.json()["detail"] == "只支持上传图片文件"


def test_episode_and_split_shots(client, flow):
    h, pid = flow["h"], flow["pid"]
    # 项目创建时已自动建好「第1集」，直接用它；再新建一集验证多集互不接收分镜
    sets = client.get("/api/video-set/list", params={"project_id": pid}, headers=h).json()
    assert [s["name"] for s in sets] == ["第1集"]
    flow["ep"] = sets[0]["id"]
    r = client.post("/api/video-set/create", json={"project_id": pid, "name": "第 2 集"}, headers=h)
    assert r.status_code == 200
    ep2 = r.json()["id"]

    r = client.post("/api/shots/split", json={"project_id": pid, "novel_paragraph": NOVEL, "video_set_id": flow["ep"]},
                    headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["data"]["count"] == 3

    shots = client.get("/api/shots", params={"project_id": pid, "video_set_id": flow["ep"]}, headers=h).json()
    assert [s["shot_no"] for s in shots] == [1, 2, 3]
    # 视频段：一条 = 一次 15 秒生成，逐句台词带说话人和类型；兼容字段 text / character_name 照旧可用
    seg = shots[1]
    assert seg["duration"] == 15 and seg["model_key"] == "seedance-2.0-fast"
    assert [ln["kind"] for ln in seg["lines"]] == ["onscreen", "narration", "inner", "narration"]
    assert seg["character_name"] == "赵虎" and seg["text"].startswith("你也配站在这里？林风没有抬头。")
    assert seg["fill_rate"] >= 0.75 and len(seg["beats"]) == 4
    assert shots[0]["character_name"] == "旁白"  # 整段没有画内台词
    # 绑定的角色/道具只保留已有资产里的名字
    assert shots[2]["characters"] == ["林风", "赵虎"] and shots[2]["props"] == ["青铜古戒"]
    # 有参考图的角色出现在“用到的资产”里
    assert any(a["type"] == "角色" for a in shots[0]["assets"])
    flow["shots"] = shots
    assert client.get("/api/shots", params={"project_id": pid, "video_set_id": ep2}, headers=h).json() == []
    # 第 2 集用完即删，后续用例只面对第一集
    assert client.delete("/api/video-set/delete", params={"set_id": ep2}, headers=h).status_code == 200

    sets = client.get("/api/video-set/list", params={"project_id": pid}, headers=h).json()
    assert sets[0]["shot_count"] == 3 and sets[0]["video_count"] == 0


def test_unassigned_shots_visible_in_episode(client, keyed_user):
    """没有剧集时拆出的分镜（video_set_id=null），建剧集后仍要能在该剧集下看到"""
    h = keyed_user["headers"]
    pid = client.post("/api/projects", json={"name": "未分组"}, headers=h).json()["data"]["id"]
    # 新项目自动带「第1集」，拆分镜默认直接归入它；
    auto = client.get("/api/video-set/list", params={"project_id": pid}, headers=h).json()[0]["id"]
    assert client.post("/api/shots/split", json={"project_id": pid, "novel_paragraph": NOVEL}, headers=h).status_code == 200
    assert len(client.get("/api/shots", params={"project_id": pid, "video_set_id": auto}, headers=h).json()) == 3
    # 老项目没有剧集：删掉自动集再拆，分镜为未分组，之后建的第一集仍要接收它们
    assert client.delete("/api/video-set/delete", params={"set_id": auto}, headers=h).status_code == 200
    assert client.post("/api/shots/split", json={"project_id": pid, "novel_paragraph": NOVEL}, headers=h).status_code == 200
    ep = client.post("/api/video-set/create", json={"project_id": pid, "name": "第 1 集"}, headers=h).json()["id"]
    shots = client.get("/api/shots", params={"project_id": pid, "video_set_id": ep}, headers=h).json()
    assert len(shots) == 3
    # 第一集创建时接收未分组分镜：镜头数、导出口径与分镜页一致
    assert client.get("/api/video-set/list", params={"project_id": pid}, headers=h).json()[0]["shot_count"] == 3
    # 之后新建的剧集不再接收
    ep2 = client.post("/api/video-set/create", json={"project_id": pid, "name": "第 2 集"}, headers=h).json()["id"]
    assert client.get("/api/shots", params={"project_id": pid, "video_set_id": ep2}, headers=h).json() == []


def test_resplit_appends_with_continuing_numbers(client, keyed_user):
    """再拆一次分镜：追加到已有镜头之后，镜号接着编，不重复"""
    h = keyed_user["headers"]
    pid = client.post("/api/projects", json={"name": "重拆"}, headers=h).json()["data"]["id"]
    for _ in range(2):
        assert client.post("/api/shots/split", json={"project_id": pid, "novel_paragraph": NOVEL}, headers=h).status_code == 200
    shots = client.get("/api/shots", params={"project_id": pid}, headers=h).json()
    assert [s["shot_no"] for s in shots] == [1, 2, 3, 4, 5, 6]


def test_update_shot_and_generate_image(client, flow):
    h = flow["h"]
    shot = flow["shots"][0]
    # 逐句改台词：后端重新校正起止，并同步兼容字段 text / character_name
    lines = [dict(ln) for ln in shot["lines"]]
    lines[0]["text"] = "暴雨倾盆。"
    lines.append({"speaker": "林风", "text": "来了。", "kind": "onscreen"})
    r = client.put(f"/api/shots/{shot['id']}", json={"lines": lines}, headers=h)
    assert r.status_code == 200, r.text
    r = client.post("/api/image/generate", json={"shot_id": shot["id"], "prompt": shot["prompt"]}, headers=h)
    assert r.status_code == 200, r.text
    _static(client, r.json()["data"]["img_path"])
    shots = client.get("/api/shots", params={"project_id": flow["pid"], "video_set_id": flow["ep"]}, headers=h).json()
    got = shots[0]
    assert got["text"].startswith("暴雨倾盆。") and got["character_name"] == "林风" and got["img_path"]
    assert got["duration"] == 15 and len(got["lines"]) == 4
    ends = [(ln["start"], ln["end"]) for ln in got["lines"]]
    assert all(a < b for a, b in ends) and all(ends[i][1] <= ends[i + 1][0] for i in range(3)) and ends[-1][1] <= 15


def test_generate_storyboard(client, flow):
    """四格分镜图（T-215）：拆分镜时存四格文案；出图写 storyboard_path（方图）；列表返回 S1–S4；
    视频提示词的分镜参考改为四格图并在【画面】时间段标格；改小镜头后文案重拼；手改文案原样保存。"""
    h, pid = flow["h"], flow["pid"]
    shot = flow["shots"][1]
    assert shot["storyboard_prompt"].startswith("【整体设定】") and "第四格（右下）" in shot["storyboard_prompt"]

    r = client.post("/api/image/storyboard", json={"shot_id": shot["id"]}, headers=h)
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["size"] in ([1024, 1024], [1280, 1280]) and "第一格（左上）" in data["prompt"]
    _static(client, data["storyboard_path"])

    shots = client.get("/api/shots", params={"project_id": pid, "video_set_id": flow["ep"]}, headers=h).json()
    got = next(s for s in shots if s["id"] == shot["id"])
    assert got["storyboard_path"] == data["storyboard_path"]
    assert [p["panel"] for p in got["storyboard_panels"]] == ["S1", "S2", "S3", "S4"]
    assert got["storyboard_panels"][0]["start"] == 0 and got["storyboard_panels"][-1]["end"] == got["duration"]
    assert any(a["type"] == "分镜参考" and a["name"] == "四格分镜" for a in got["assets"])
    fvp = got["final_video_prompt"]
    assert "本段四格分镜（左上→右上→左下→右下" in fvp and "S1 左上格]" in fvp and "本段首帧画面参考" not in fvp

    # 改小镜头 → 四格文案重拼；手改文案 → 原样保存，不被覆盖
    beats = [dict(b, action="赵虎把扫帚踢到一边") for b in got["beats"]]
    r = client.put(f"/api/shots/{shot['id']}", json={"beats": beats}, headers=h)
    assert r.status_code == 200 and "赵虎把扫帚踢到一边" in r.json()["data"]["storyboard_prompt"]
    r = client.put(f"/api/shots/{shot['id']}", json={"storyboard_prompt": "我手写的四格"}, headers=h)
    assert r.status_code == 200
    got = next(s for s in client.get("/api/shots", params={"project_id": pid}, headers=h).json() if s["id"] == shot["id"])
    assert got["storyboard_prompt"] == "我手写的四格"
    # 旧格式镜头（没有小镜头）不能出四格图
    legacy = client.post("/api/shots", json={"project_id": pid, "shot_no": 99, "text": "旧镜头"}, headers=h).json()["data"]["id"]
    assert client.post("/api/image/storyboard", json={"shot_id": legacy}, headers=h).status_code == 400
    assert client.delete(f"/api/shots/{legacy}", headers=h).status_code == 200


def test_video_generate_single(client, flow, video_accounts):
    h = flow["h"]
    shot = flow["shots"][0]
    r = client.post("/api/video/generate/single", params={"shot_id": shot["id"]}, headers=h)
    assert r.status_code == 200, r.text
    vp = r.json()["data"]["video_path"]
    assert vp.startswith("videos/") and b"ftyp" in _static(client, vp).content[:64]

    # 账号列表不返回 cookie；生成时读到的（替身）会员额度写回账号，按额度计算剩余
    accounts = client.get("/api/video/accounts", headers=h).json()["data"]["accounts"]
    assert accounts and all("cookies" not in a and a["limit_mode"] in ("member", "daily") for a in accounts)
    used = next(a for a in accounts if a["name"] == r.json()["data"]["account_name"])
    assert used["limit_mode"] == "member" and used["quota"]["plan_name"] == "标准套餐"
    assert used["quota"]["total"] == 16100 and used["remaining_estimate"] is None
    others = [a for a in accounts if a["id"] != used["id"] and a["id"].startswith("e2e_account_")]
    assert others and all(a["limit_mode"] == "daily" and a["remaining_estimate"] == 2 for a in others)
    status = client.get("/api/video/accounts/status", headers=h).json()["data"]
    assert all("cookies" not in a for a in status["accounts"]) and status["parallel_max"] >= 1


def test_video_generate_batch_with_sse(client, flow, video_accounts, api_base):
    """批量（并行模式，前端用的就是它）：SSE 推送 JSON 进度，视频写回分镜"""
    h, pid = flow["h"], flow["pid"]
    events, ready = [], threading.Event()

    def listen():
        with httpx.Client(base_url=api_base, timeout=30, trust_env=False) as c:
            with c.stream("GET", f"/api/video/events/{pid}") as r:
                ready.set()
                for line in r.iter_lines():
                    if line.startswith("data:"):
                        events.append(json.loads(line[5:].strip()))
                        if sum(1 for e in events if e["step"] == "done") >= 2:
                            return

    t = threading.Thread(target=listen, daemon=True)
    t.start()
    assert ready.wait(10)
    status = client.get("/api/video/accounts/status", headers=h).json()["data"]
    assert status["total_available_quota"] >= 2

    r = client.post("/api/video/generate/batch", params={"project_id": pid, "limit": 2, "parallel": True}, headers=h)
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert d["success_count"] == 2 and d["failed_count"] == 0
    t.join(10)
    assert {e["shot_no"] for e in events if e["step"] == "done"} == {2, 3}

    sets = client.get("/api/video-set/list", params={"project_id": pid}, headers=h).json()
    assert sets[0]["video_count"] == 3
    # 并行模式也要计入账号今日用量
    used = sum(a["today_used"] for a in client.get("/api/video/accounts/status", headers=h).json()["data"]["accounts"])
    assert used == 2
    r = client.post("/api/video/generate/batch", params={"project_id": pid, "parallel": True}, headers=h)
    assert r.status_code == 404 and r.json()["detail"] == "所有分镜都已生成视频"


def test_manual_video_upload(client, flow):
    h = flow["h"]
    mp4 = (Path(__file__).parent / "fixtures" / "clip.mp4").read_bytes()
    shot = flow["shots"][2]
    r = client.post(f"/api/video/shots/{shot['id']}/upload-video", files={"file": ("c.mp4", mp4, "video/mp4")}, headers=h)
    assert r.status_code == 200, r.text
    _static(client, r.json()["data"]["video_path"])


def test_voice_assign_and_tts(client, flow):
    h, pid = flow["h"], flow["pid"]
    voices = client.get("/api/tts/voices", headers=h).json()["data"]["voices"]
    assert len(voices) >= 10

    r = client.post("/api/tts/auto-assign", params={"project_id": pid}, headers=h)
    assert r.status_code == 200, r.text
    chars = client.get("/api/characters", params={"project_id": pid}, headers=h).json()
    assert all(c["voice_name"] for c in chars)

    shot = flow["shots"][1]
    r = client.post("/api/tts/generate", json={"shot_id": shot["id"], "text": shot["text"]}, headers=h)
    assert r.status_code == 200, r.text
    audio = _static(client, r.json()["data"]["audio_path"])
    assert len(audio.content) > 1000
    # 多句段：逐句生成，按段内时间拼成一条，返回每句实际起止（不重叠）
    tl = r.json()["data"]["timeline"]
    assert r.json()["data"]["lines"] == 4 and len(tl) == 4
    assert all(tl[i]["end"] <= tl[i + 1]["start"] for i in range(3)) and tl[0]["start"] == 0.5


def test_srt_export_and_download(client, flow):
    h, pid = flow["h"], flow["pid"]
    r = client.post("/api/tts/srt/export", json={"project_id": pid}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["data"]["shot_count"] == 3
    # 前端用 window.open 下载，只能靠查询参数带 token
    r = client.get(f"/api/tts/srt/download/{pid}", params={"token": flow["token"]})
    assert r.status_code == 200
    body = r.content.decode("utf-8")
    # 视频段逐句出字幕：第一句在段内 0.5 秒开始
    assert "00:00:00,500 -->" in body and "你也配站在这里？" in body


def test_export_jianying(client, flow):
    h, pid = flow["h"], flow["pid"]
    r = client.get("/api/video/export/jianying", params={"project_id": pid, "video_set_id": flow["ep"]}, headers=h)
    assert r.status_code == 200
    d = r.json()
    assert d["ok"] is True, d
    draft_dir = Path(os.environ["JIANYING_DRAFT_DIR"]) / d["draft"]
    info = json.loads((draft_dir / "draft_info.json").read_text())
    assert len(info["materials"]["videos"]) == 3
    assert all(Path(v["path"]).exists() for v in info["materials"]["videos"])


def test_episode_rename_and_delete(client, flow):
    h, pid = flow["h"], flow["pid"]
    r = client.post("/api/video-set/rename", params={"set_id": flow["ep"]}, json={"name": "第一集·暴雨"}, headers=h)
    assert r.status_code == 200
    sets = client.get("/api/video-set/list", params={"project_id": pid}, headers=h).json()
    assert sets[0]["name"] == "第一集·暴雨"
    assert client.delete("/api/video-set/delete", params={"set_id": flow["ep"]}, headers=h).status_code == 200
    assert client.get("/api/video-set/list", params={"project_id": pid}, headers=h).json() == []
    # 删除剧集同时删除其下分镜
    assert client.get("/api/shots", params={"project_id": pid}, headers=h).json() == []


def test_legacy_project_novel_migrates_to_first_episode(client):
    """老作品：小说存在项目上、没有集。列集时自动建第1集并搬入小说，转剧本才读得到正文。"""
    from bson import ObjectId
    from db.sync_client import get_sync_db
    h = register(client, "legacy")["headers"]
    pid = client.post("/api/projects", json={"name": "老作品"}, headers=h).json()["data"]["id"]
    for s in client.get("/api/video-set/list", params={"project_id": pid}, headers=h).json():
        client.delete("/api/video-set/delete", params={"set_id": s["id"]}, headers=h)
    get_sync_db().projects.update_one({"_id": ObjectId(pid)}, {"$set": {"novel_content": "老小说正文"}})
    got = client.get("/api/video-set/list", params={"project_id": pid}, headers=h).json()
    assert len(got) == 1 and got[0]["name"] == "第1集" and got[0]["novel_content"] == "老小说正文"
    again = client.get("/api/video-set/list", params={"project_id": pid}, headers=h).json()
    assert len(again) == 1
