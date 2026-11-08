"""错误与空状态"""
from conftest import register

OTHER_ID = "0123456789abcdef01234567"


def test_extract_without_api_key(client, user):
    """没配密钥时提取要给出明确提示，而不是 500"""
    h = user["headers"]
    pid = client.post("/api/projects", json={"name": "无密钥"}, headers=h).json()["data"]["id"]
    r = client.post("/api/assets/extract-all", json={"project_id": pid, "novel_text": "一段小说"}, headers=h)
    assert r.status_code == 400
    assert "密钥" in r.json()["detail"]
    r = client.post("/api/shots/split", json={"project_id": pid, "novel_paragraph": "一段小说"}, headers=h)
    assert r.status_code == 400


def test_novel_generate_without_key_reports_error(client, user):
    h = user["headers"]
    pid = client.post("/api/projects", json={"name": "无密钥"}, headers=h).json()["data"]["id"]
    r = client.post("/api/novel/generate", json={"project_id": pid, "genre": "玄幻", "style": "xuanhuan",
                                                 "outline": "x", "protagonist": "y"}, headers=h)
    assert r.status_code == 400


def test_project_not_found_paths(client, keyed_user):
    h = keyed_user["headers"]
    assert client.post("/api/assets/extract-all", json={"project_id": OTHER_ID, "novel_text": "x"}, headers=h).status_code == 404
    assert client.post("/api/shots/split", json={"project_id": "bad", "novel_paragraph": "x"}, headers=h).status_code == 400
    assert client.post("/api/tts/srt/export", json={"project_id": OTHER_ID}, headers=h).status_code == 404
    assert client.get("/api/video/export/jianying", params={"project_id": OTHER_ID}, headers=h).status_code == 404


def test_empty_project_states(client, project, video_accounts):
    """新作品：没有分镜、没有角色、没有视频时各接口的空状态"""
    h = project["user"]["headers"]
    pid = project["id"]
    assert client.get("/api/shots", params={"project_id": pid}, headers=h).json() == []
    assert client.get("/api/characters", params={"project_id": pid}, headers=h).json() == []
    assert client.get("/api/video-set/list", params={"project_id": pid}, headers=h).json() == []

    r = client.post("/api/tts/srt/export", json={"project_id": pid}, headers=h)
    assert r.status_code == 404 and r.json()["detail"] == "该项目没有分镜数据"
    r = client.get(f"/api/tts/srt/download/{pid}", headers=h)
    assert r.status_code == 404
    r = client.post("/api/tts/auto-assign", params={"project_id": pid}, headers=h)
    assert r.status_code == 400 and "没有角色" in r.json()["detail"]
    r = client.post("/api/video/generate/batch", params={"project_id": pid, "parallel": True}, headers=h)
    assert r.status_code == 404
    r = client.get("/api/video/export/jianying", params={"project_id": pid}, headers=h)
    assert r.status_code == 200 and r.json() == {"ok": False, "msg": "没有已生成的视频"}


def test_polish_empty_text(client, project):
    h = project["user"]["headers"]
    r = client.post("/api/novel/polish", json={"project_id": project["id"], "text": "   "}, headers=h)
    assert r.status_code == 400 and r.json()["detail"] == "待润色文本不能为空"


def test_shot_and_asset_not_found(client, keyed_user):
    h = keyed_user["headers"]
    assert client.put(f"/api/shots/{OTHER_ID}", json={"text": "x"}, headers=h).status_code == 404
    assert client.delete(f"/api/shots/bad-id", headers=h).status_code == 400
    assert client.post("/api/image/generate", json={"shot_id": OTHER_ID, "prompt": "x"}, headers=h).status_code == 404
    assert client.post("/api/tts/generate", json={"shot_id": OTHER_ID, "text": "x"}, headers=h).status_code == 404
    r = client.post("/api/assets/generate", json={"asset_type": "monster", "asset_id": OTHER_ID}, headers=h)
    assert r.status_code == 400
    assert client.post("/api/video/generate/single", params={"shot_id": OTHER_ID}, headers=h).status_code == 404


def test_other_users_shots_hidden(client, project):
    h = project["user"]["headers"]
    pid = project["id"]
    client.post("/api/shots/split", json={"project_id": pid, "novel_paragraph": "林风与赵虎对峙"}, headers=h)
    shot = client.get("/api/shots", params={"project_id": pid}, headers=h).json()[0]
    other = register(client, "spy")
    assert client.get("/api/shots", params={"project_id": pid}, headers=other["headers"]).json() == []
    assert client.put(f"/api/shots/{shot['id']}", json={"text": "改"}, headers=other["headers"]).status_code == 404


def test_model_presets_crud(client, user, mongo):
    """模型预设落在当前库（MONGODB_DB_NAME），不是写死的 dongai"""
    r = client.post("/api/models", json={"name": "E2E 预设", "provider": "zhipu", "models": "glm-4.5-flash",
                                         "api_keys": "k1\nk2"})
    assert r.status_code == 200
    mid = r.json()["id"]
    assert mongo.llm_models.count_documents({"name": "E2E 预设"}) == 1
    row = next(m for m in client.get("/api/models").json()["data"] if m["_id"] == mid)
    assert row["api_keys"] == ["k1", "k2"] and row["models"] == ["glm-4.5-flash"]
    assert client.delete(f"/api/models/{mid}").status_code == 200
    assert mongo.llm_models.count_documents({"name": "E2E 预设"}) == 0
