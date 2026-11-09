"""作品 CRUD 与权限隔离"""
from conftest import register


def test_project_crud(client, user):
    h = user["headers"]
    assert client.get("/api/projects", headers=h).json() == []

    r = client.post("/api/projects", json={"name": "第一部", "genre": "都市"}, headers=h)
    assert r.status_code == 200
    pid = r.json()["data"]["id"]

    listed = client.get("/api/projects", headers=h).json()
    assert [p["id"] for p in listed] == [pid]
    assert listed[0]["name"] == "第一部" and listed[0]["genre"] == "都市"

    r = client.put(f"/api/projects/{pid}", json={"name": "改名了", "style": "dushi", "novel_content": "正文"}, headers=h)
    assert r.status_code == 200
    got = client.get(f"/api/projects/{pid}", headers=h).json()
    assert got["name"] == "改名了" and got["style"] == "dushi" and got["novel_content"] == "正文"

    assert client.delete(f"/api/projects/{pid}", headers=h).status_code == 200
    assert client.get(f"/api/projects/{pid}", headers=h).status_code == 404


def test_project_validation_and_bad_id(client, user):
    h = user["headers"]
    assert client.post("/api/projects", json={"name": ""}, headers=h).status_code == 422
    assert client.get("/api/projects/not-an-id", headers=h).status_code == 400
    assert client.get("/api/projects/0123456789abcdef01234567", headers=h).status_code == 404


def test_projects_isolated_between_users(client, project):
    other = register(client, "other")
    h = other["headers"]
    pid = project["id"]
    assert client.get("/api/projects", headers=h).json() == []
    assert client.get(f"/api/projects/{pid}", headers=h).status_code == 404
    assert client.put(f"/api/projects/{pid}", json={"name": "x"}, headers=h).status_code == 404
    assert client.delete(f"/api/projects/{pid}", headers=h).status_code == 404


def test_delete_project_cascades(client, project, mongo):
    """删除作品时角色、场景、道具、分镜、剧集一并删除"""
    h = project["user"]["headers"]
    pid = project["id"]
    client.post("/api/video-set/create", json={"project_id": pid, "name": "第 1 集"}, headers=h)
    r = client.post("/api/assets/extract-all", json={"project_id": pid, "novel_text": "林风与赵虎在演武场对峙。"}, headers=h)
    assert r.status_code == 200, r.text
    assert client.post("/api/shots/split", json={"project_id": pid, "novel_paragraph": "林风与赵虎在演武场对峙。"},
                       headers=h).status_code == 200

    assert client.delete(f"/api/projects/{pid}", headers=h).status_code == 200
    for col in ("characters", "scenes", "props", "shots", "video_sets"):
        assert mongo[col].count_documents({"project_id": pid}) == 0, col
