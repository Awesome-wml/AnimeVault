"""文生图模型预设（model_type=image）与出图模型选择：替身模式。"""
import io

import pytest

from conftest import sse_done
from core.providers.fake import FAKE_NOVEL
from core.providers.image_provider import image_size


def _create(client, body):
    r = client.post("/api/models", json=body)
    assert r.status_code == 200, r.text
    return r.json()["id"]


@pytest.fixture
def image_preset(client):
    mid = _create(client, {"name": "e2e 文生图", "provider": "zhipu", "model_type": "image",
                           "models": "cogview-3-flash\nglm-image", "api_keys": ""})
    yield mid
    client.delete(f"/api/models/{mid}")


def test_model_type_normalized(client, image_preset):
    rows = client.get("/api/models").json()["data"]
    got = next(r for r in rows if r["_id"] == image_preset)
    assert got["model_type"] == "image" and got["models"] == ["cogview-3-flash", "glm-image"]
    # 非法类型按对话处理；旧记录没有类型时列表里补成 chat
    bad = _create(client, {"name": "e2e 非法类型", "provider": "zhipu", "model_type": "video", "models": "glm-4"})
    try:
        assert next(r for r in client.get("/api/models").json()["data"] if r["_id"] == bad)["model_type"] == "chat"
    finally:
        client.delete(f"/api/models/{bad}")


def test_default_is_per_type(client, image_preset):
    """设文生图默认不影响对话默认，反之亦然。"""
    chat = _create(client, {"name": "e2e 对话", "provider": "zhipu", "models": "glm-4.5-flash"})
    try:
        assert client.post(f"/api/models/{chat}/default").status_code == 200
        assert client.post(f"/api/models/{image_preset}/default").status_code == 200
        rows = {r["_id"]: r for r in client.get("/api/models").json()["data"]}
        assert rows[chat]["is_default"] and rows[image_preset]["is_default"]
        assert sum(1 for r in rows.values() if r.get("is_default") and r["model_type"] == "image") == 1
        assert sum(1 for r in rows.values() if r.get("is_default") and r["model_type"] == "chat") == 1
    finally:
        client.delete(f"/api/models/{chat}")


def test_asset_generate_with_image_model(client, project, image_preset):
    """资产出图可选文生图预设与子模型：尺寸按模型档位，角色横版、道具/场景方形。"""
    h, pid = project["user"]["headers"], project["id"]
    sse_done(client.post("/api/assets/extract-all", json={"project_id": pid, "novel_text": FAKE_NOVEL}, headers=h))
    char = client.get("/api/characters", params={"project_id": pid}, headers=h).json()[0]
    prop = client.get("/api/props", params={"project_id": pid}, headers=h).json()[0]

    r = client.post("/api/assets/generate", json={"asset_type": "character", "asset_id": char["id"],
                                                  "model_id": image_preset, "model": "glm-image"}, headers=h)
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["model"] == "glm-image" and data["size"] == list(image_size("glm-image", "landscape"))

    # 不选子模型：用预设第一个；道具方形
    r = client.post("/api/assets/generate", json={"asset_type": "prop", "asset_id": prop["id"],
                                                  "model_id": image_preset}, headers=h)
    data = r.json()["data"]
    assert data["model"] == "cogview-3-flash" and data["size"] == [1024, 1024]

    # 选了对话模型预设：不当文生图用，回退账号默认文生图模型
    chat = _create(client, {"name": "e2e 对话2", "provider": "zhipu", "models": "glm-4.5-flash"})
    try:
        r = client.post("/api/assets/generate", json={"asset_type": "prop", "asset_id": prop["id"],
                                                      "model_id": chat}, headers=h)
        assert r.json()["data"]["model"] != "glm-4.5-flash"
    finally:
        client.delete(f"/api/models/{chat}")


def test_character_sheet_custom_prompt(client, project):
    """角色出图可选自建的“角色三视图”提示词（prompt_id）。"""
    h, pid = project["user"]["headers"], project["id"]
    sse_done(client.post("/api/assets/extract-all", json={"project_id": pid, "novel_text": FAKE_NOVEL}, headers=h))
    char = client.get("/api/characters", params={"project_id": pid}, headers=h).json()[0]
    r = client.post("/api/prompts", json={"name": "e2e 三视图", "type": "character_sheet",
                                          "content": "自定义三视图：{character_name}，{art_style}"})
    assert r.status_code == 200, r.text
    prompt_id = r.json()["id"]
    try:
        r = client.post("/api/assets/generate", json={"asset_type": "character", "asset_id": char["id"],
                                                      "prompt_id": prompt_id}, headers=h)
        assert r.status_code == 200, r.text
    finally:
        client.delete(f"/api/prompts/{prompt_id}")


def test_image_size_tiers():
    assert image_size("glm-image", "square") == (1280, 1280)
    assert image_size("cogview-3-flash", "landscape") == (1344, 768)
    assert image_size(None, "portrait") == (768, 1344)


def test_face_grid_skips_without_deps_or_applies():
    from core import face_grid
    png = (__import__("pathlib").Path(__file__).parent / "fixtures" / "placeholder.png").read_bytes()
    out = face_grid.apply_face_grid(png)
    if not face_grid.available():
        assert out == png  # 缺 numpy / Pillow：原样返回，不影响出图
    else:
        from PIL import Image
        assert Image.open(io.BytesIO(out)).size == Image.open(io.BytesIO(png)).size
