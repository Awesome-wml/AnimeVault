"""文生图模型预设（model_type=image）与出图模型选择：替身模式。"""
import io

import pytest

from conftest import sse_done
from core.providers.fake import FAKE_NOVEL
from core.providers.image_provider import image_size


def _create(models_client, body):
    r = models_client.post("/api/models", json=body)
    assert r.status_code == 200, r.text
    return r.json()["id"]


@pytest.fixture
def image_preset(client, models_client):
    mid = _create(models_client, {"name": "e2e 文生图", "provider": "zhipu", "model_type": "image",
                           "models": "cogview-3-flash\nglm-image", "api_keys": ""})
    yield mid
    models_client.delete(f"/api/models/{mid}")


def test_models_listed_with_purpose(client, image_preset, models_client):
    """每条预设都有用途（chat / image）：手动标的照用，没标或乱标的按模型名判断。"""
    rows = models_client.get("/api/models").json()["data"]
    got = next(r for r in rows if r["_id"] == image_preset)
    assert got["models"] == ["cogview-3-flash", "glm-image"] and got["model_type"] == "image" and got["kinds"] == ["image"]
    guessed = _create(models_client, {"name": "e2e 没标类型", "provider": "other", "models": "doubao-seedream-5-5-261028"})
    bad = _create(models_client, {"name": "e2e 乱标类型", "provider": "zhipu", "model_type": "video", "models": "glm-4"})
    try:
        rows = {r["_id"]: r for r in models_client.get("/api/models").json()["data"]}
        assert rows[guessed]["model_type"] == "auto" and rows[guessed]["kinds"] == ["image"]
        assert rows[bad]["model_type"] == "auto" and rows[bad]["kinds"] == ["chat"]
    finally:
        models_client.delete(f"/api/models/{guessed}")
        models_client.delete(f"/api/models/{bad}")


def test_default_unique_per_purpose(client, image_preset, models_client):
    """默认按用途各一个：把出图预设设为默认，不会顶掉对话默认；同用途内只留一个默认。"""
    rows0 = models_client.get("/api/models").json()["data"]
    before = [r["_id"] for r in rows0 if r.get("is_default")]
    chat = _create(models_client, {"name": "e2e 对话", "provider": "zhipu", "models": "glm-4.5-flash"})
    chat2 = _create(models_client, {"name": "e2e 对话2", "provider": "zhipu", "models": "glm-4.5-flash"})
    try:
        assert models_client.post(f"/api/models/{chat}/default").status_code == 200
        assert models_client.post(f"/api/models/{image_preset}/default").status_code == 200
        rows = {r["_id"]: r for r in models_client.get("/api/models").json()["data"]}
        assert rows[image_preset]["is_default"] and rows[chat]["is_default"]
        assert models_client.post(f"/api/models/{chat2}/default").status_code == 200
        rows = {r["_id"]: r for r in models_client.get("/api/models").json()["data"]}
        assert rows[chat2]["is_default"] and not rows[chat]["is_default"] and rows[image_preset]["is_default"]
        for kind in ("chat", "image"):
            assert sum(1 for r in rows.values() if r.get("is_default") and kind in r["kinds"]) == 1
    finally:
        models_client.delete(f"/api/models/{chat}")
        models_client.delete(f"/api/models/{chat2}")
        for mid in before:
            models_client.post(f"/api/models/{mid}/default")


def test_asset_generate_with_image_model(client, project, image_preset, models_client):
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

    # 类型不再区分：选中哪个预设就用哪个，对话预设也会被采用
    chat = _create(models_client, {"name": "e2e 对话2", "provider": "zhipu", "models": "glm-4.5-flash"})
    try:
        r = client.post("/api/assets/generate", json={"asset_type": "prop", "asset_id": prop["id"],
                                                      "model_id": chat}, headers=h)
        assert r.json()["data"]["model"] == "glm-4.5-flash"
    finally:
        models_client.delete(f"/api/models/{chat}")


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
