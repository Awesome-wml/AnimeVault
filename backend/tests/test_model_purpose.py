"""什么环节用什么模型：预设的用途（对话 / 出图）、按用途取默认、用错类型拦住。不连数据库。"""
import pytest
from bson import ObjectId
from fastapi import HTTPException

from core import llm_factory as F
from core.providers.image_provider import is_image_model, model_kind, models_of_kind, preset_kinds


def test_image_model_names():
    for m in ("doubao-seedream-5-5-261028", "Doubao-SeedEdit-3.0", "cogview-3-flash", "glm-image", "gpt-image-2",
              "dall-e-3", "gemini-2.5-flash-image", "imagen-4", "flux-2-pro"):
        assert is_image_model(m), m
    for m in ("glm-5.3-flashx", "glm-4.5-flash", "deepseek-chat", "gpt-5", "gemini-2.5-flash", "doubao-seed-1-6", None, ""):
        assert not is_image_model(m), m


def test_kind_manual_wins_then_guess():
    assert preset_kinds({"models": ["glm-4.5-flash"]}) == {"chat"}
    assert preset_kinds({"models": ["cogview-3-flash", "glm-image"]}) == {"image"}
    assert preset_kinds({"model": "doubao-seedream-5-5-261028", "model_type": "auto"}) == {"image"}
    assert preset_kinds({"model_type": "chat", "models": ["my-image-captioner"]}) == {"chat"}   # 手动标的优先
    assert preset_kinds({"model_type": "video", "models": ["glm-4"]}) == {"chat"}              # 不认识的值按名字判断
    assert preset_kinds(None) == {"chat"}
    # 一条预设里混放对话模型和出图模型：各归各的
    mixed = {"models": ["glm-5.3-flashx", "glm-image"]}
    assert preset_kinds(mixed) == {"chat", "image"}
    assert models_of_kind(mixed, "chat") == ["glm-5.3-flashx"] and models_of_kind(mixed, "image") == ["glm-image"]
    assert model_kind(mixed, "glm-image") == "image"


class _Col:
    def __init__(self, rows):
        self.rows = rows

    def find_one(self, q):
        return next((r for r in self.rows if r["_id"] == q["_id"]), None)

    def find(self, q=None):
        return [r for r in self.rows if all(r.get(k) == v for k, v in (q or {}).items())]


class _Db:
    def __init__(self, rows):
        self.llm_models = _Col(rows)


@pytest.fixture
def presets(monkeypatch):
    chat = {"_id": ObjectId(), "name": "智谱对话", "provider": "zhipu", "models": ["glm-5.3-flashx"], "api_keys": ["zk"],
            "base_url": "https://open.bigmodel.cn/api/paas/v4"}
    seedream = {"_id": ObjectId(), "name": "Seedream 5.5 出图", "provider": "volcengine", "is_default": True,
                "models": ["doubao-seedream-5-5-261028"], "api_keys": ["ark"],
                "base_url": "https://ark.cn-beijing.volces.com/api/v3"}
    cog = {"_id": ObjectId(), "name": "智谱出图", "provider": "zhipu", "model_type": "image",
           "models": ["cogview-3-flash", "glm-image"], "api_keys": []}
    rows = [chat, seedream, cog]
    monkeypatch.setattr(F, "_db", _Db(rows))
    return {"chat": chat, "seedream": seedream, "cog": cog, "rows": rows}


USER = {"doubao_api_key": "global", "doubao_base_url": "https://open.bigmodel.cn/api/paas/v4", "doubao_model": "glm-4.5-flash"}


def test_image_without_selection_uses_default_image_preset(presets):
    """没在页面上选出图模型时，用“默认出图预设”——原来直接落到账号设置的 cogview-3-flash。"""
    p = F.build_image_provider(USER)
    assert p.model == "doubao-seedream-5-5-261028" and p.base_url.startswith("https://ark.") and p.api_key == "ark"
    assert "默认出图预设" in p.source


def test_image_default_does_not_hijack_text(presets):
    """出图预设被设为默认，不影响文字环节：没有对话默认时沿用账号设置。"""
    p = F.build_provider(USER)
    assert p.model == "glm-4.5-flash" and p.api_key == "global"
    presets["chat"]["is_default"] = True
    assert F.build_provider(USER).model == "glm-5.3-flashx"


def test_selected_preset_and_submodel(presets):
    p = F.build_image_provider(USER, str(presets["cog"]["_id"]), "glm-image")
    assert p.model == "glm-image" and p.api_key == "global" and "页面选的预设" in p.source
    assert F.build_provider(USER, str(presets["chat"]["_id"])).model == "glm-5.3-flashx"


def test_wrong_purpose_is_rejected_with_reason(presets):
    with pytest.raises(HTTPException) as e:
        F.build_provider(USER, str(presets["seedream"]["_id"]))
    assert e.value.status_code == 400 and "出图模型" in e.value.detail and "对话模型" in e.value.detail
    with pytest.raises(HTTPException) as e:
        F.build_image_provider(USER, str(presets["chat"]["_id"]))
    assert "对话模型" in e.value.detail and "出图模型" in e.value.detail
    with pytest.raises(HTTPException) as e:
        F.build_image_provider(USER, str(ObjectId()))
    assert "已被删除" in e.value.detail


def test_no_default_falls_back_to_account(presets):
    presets["seedream"]["is_default"] = False
    p = F.build_image_provider(USER)
    assert p.model == "cogview-3-flash" and "账号设置" in p.source


def test_mixed_preset_serves_both_purposes(presets):
    """一条预设里既有对话模型又有出图模型：文字用它的对话模型，出图用它的出图模型，选错子模型才拦。"""
    presets["seedream"]["is_default"] = False
    mixed = {"_id": ObjectId(), "name": "智谱全家桶", "provider": "zhipu", "is_default": True,
             "models": ["glm-5.3-flashx", "glm-image"], "api_keys": ["zk"]}
    presets["rows"].append(mixed)
    assert F.build_provider(USER).model == "glm-5.3-flashx"
    assert F.build_image_provider(USER).model == "glm-image"
    mid = str(mixed["_id"])
    assert F.build_provider(USER, mid).model == "glm-5.3-flashx"
    assert F.build_image_provider(USER, mid).model == "glm-image"
    with pytest.raises(HTTPException) as e:
        F.build_provider(USER, mid, "glm-image")
    assert "glm-image" in e.value.detail
