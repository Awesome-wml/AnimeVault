"""主流程（替身模式）：小说 → 提取资产 → 风格 → 资产出图 → 拆分镜 → 画面 → 视频 → 配音 → 字幕 → 剪映 → 剧集

按文件内顺序执行，后一步依赖前一步写入的数据（共享 flow 状态）。
"""
import json
import os
import threading
from pathlib import Path

import httpx
import pytest

from conftest import register

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
    assert proj["novel_content"].startswith("暴雨演武场")
    assert proj["style"] == "xuanhuan" and proj["genre"] == "玄幻"


def test_novel_save_and_polish(client, flow):
    h, pid = flow["h"], flow["pid"]
    r = client.post("/api/novel/save", params={"project_id": pid, "content": NOVEL}, headers=h)
    assert r.status_code == 200
    assert client.get(f"/api/projects/{pid}", headers=h).json()["novel_content"] == NOVEL

    r = client.post("/api/novel/polish", json={"project_id": pid, "text": NOVEL, "person": "third"}, headers=h)
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["text"].startswith("（润色稿）") and data["source_length"] == len(NOVEL)
    # 润色只返回结果，不覆盖原文
    assert client.get(f"/api/projects/{pid}", headers=h).json()["novel_content"] == NOVEL


def test_extract_all_assets(client, flow):
    h, pid = flow["h"], flow["pid"]
    r = client.post("/api/assets/extract-all", json={"project_id": pid, "novel_text": NOVEL}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["data"] == {"characters": 3, "props": 1, "scenes": 1}

    chars = client.get("/api/characters", params={"project_id": pid}, headers=h).json()
    assert {c["name"] for c in chars} == {"林风", "赵虎", "苏婉"}
    main = next(c for c in chars if c["name"] == "林风")
    assert main["importance"] == "main" and main["gender"] == "male" and main["age_group"] == "少年"
    assert [s["name"] for s in client.get("/api/scenes", params={"project_id": pid}, headers=h).json()] == ["暴雨萧瑟演武场"]
    assert [p["name"] for p in client.get("/api/props", params={"project_id": pid}, headers=h).json()] == ["青铜古戒"]


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
    r = client.post("/api/video-set/create", json={"project_id": pid, "name": "第 1 集"}, headers=h)
    assert r.status_code == 200
    flow["ep"] = r.json()["id"]

    r = client.post("/api/shots/split", json={"project_id": pid, "novel_paragraph": NOVEL, "video_set_id": flow["ep"]},
                    headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["data"]["count"] == 3

    shots = client.get("/api/shots", params={"project_id": pid, "video_set_id": flow["ep"]}, headers=h).json()
    assert [s["shot_no"] for s in shots] == [1, 2, 3]
    assert shots[1]["character_name"] == "赵虎" and shots[1]["text"] == "你也配站在这里？"
    # 绑定的角色/道具只保留已有资产里的名字
    assert shots[2]["characters"] == ["林风", "赵虎"] and shots[2]["props"] == ["青铜古戒"]
    # 有参考图的角色出现在“用到的资产”里
    assert any(a["type"] == "角色" for a in shots[0]["assets"])
    flow["shots"] = shots

    sets = client.get("/api/video-set/list", params={"project_id": pid}, headers=h).json()
    assert sets[0]["shot_count"] == 3 and sets[0]["video_count"] == 0


def test_unassigned_shots_visible_in_episode(client, keyed_user):
    """没有剧集时拆出的分镜（video_set_id=null），建剧集后仍要能在该剧集下看到"""
    h = keyed_user["headers"]
    pid = client.post("/api/projects", json={"name": "未分组"}, headers=h).json()["data"]["id"]
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
    r = client.put(f"/api/shots/{shot['id']}", json={"text": "暴雨倾盆。", "duration": 3.5}, headers=h)
    assert r.status_code == 200
    r = client.post("/api/image/generate", json={"shot_id": shot["id"], "prompt": shot["prompt"]}, headers=h)
    assert r.status_code == 200, r.text
    _static(client, r.json()["data"]["img_path"])
    shots = client.get("/api/shots", params={"project_id": flow["pid"], "video_set_id": flow["ep"]}, headers=h).json()
    assert shots[0]["text"] == "暴雨倾盆。" and shots[0]["duration"] == 3.5 and shots[0]["img_path"]


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


def test_srt_export_and_download(client, flow):
    h, pid = flow["h"], flow["pid"]
    r = client.post("/api/tts/srt/export", json={"project_id": pid}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["data"]["shot_count"] == 3
    # 前端用 window.open 下载，只能靠查询参数带 token
    r = client.get(f"/api/tts/srt/download/{pid}", params={"token": flow["token"]})
    assert r.status_code == 200
    body = r.content.decode("utf-8")
    assert "00:00:00,000 -->" in body and "你也配站在这里？" in body


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
