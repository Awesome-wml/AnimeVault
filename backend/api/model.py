"""LLM 模型预设管理 API"""
from fastapi import APIRouter, Depends, HTTPException
from db.sync_client import get_sync_db
from bson import ObjectId
from datetime import datetime

from core.providers import model_caps
from core.providers.model_caps import THINKING_MODES

from api.auth import get_current_user

# 模型预设里存着 API Key：整组接口都要求登录（服务端/docker 模式下原来不登录就能读写、改 base_url 截获 Key）
router = APIRouter(prefix="/api/models", tags=["模型管理"], dependencies=[Depends(get_current_user)])

KEY_MASK = "****"


def mask_key(key: str) -> str:
    """接口只回掩码后的 Key：sk-abcdef123456 → sk-a****3456；8 位以内全掩。"""
    k = str(key or "")
    if len(k) <= 8:
        return KEY_MASK
    return f"{k[:4]}{KEY_MASK}{k[-4:]}"


def _restore_masked_keys(keys: list, old_keys: list) -> list:
    """编辑时前端把掩码原样送回：掩码能对上的换回库里的原 Key，对不上的掩码丢弃（不能把掩码当 Key 存）。"""
    by_mask = {mask_key(k): k for k in old_keys or []}
    out = []
    for k in keys:
        if KEY_MASK in k:
            if k in by_mask:
                out.append(by_mask[k])
            continue
        out.append(k)
    return out

db = get_sync_db()

# 供应商及其默认接入地址（OpenAI 兼容接口）
PROVIDERS = {
    "zhipu": {"label": "智谱 GLM", "base_url": "https://open.bigmodel.cn/api/paas/v4"},
    "deepseek": {"label": "DeepSeek", "base_url": "https://api.deepseek.com/v1"},
    "openai": {"label": "OpenAI", "base_url": "https://api.openai.com/v1"},
    "gemini": {"label": "Google Gemini", "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/"},
    # suggest_*：前端选中这个供应商时，名称 / 模型 ID 还空着就自动填上（可改）
    "volcengine": {"label": "火山方舟（豆包 Seedream）", "base_url": "https://ark.cn-beijing.volces.com/api/v3",
                   "suggest_name": "Seedream 5.5 出图", "suggest_models": ["doubao-seedream-5-5-261028"]},
    "other": {"label": "其他", "base_url": ""},
}

# 内置默认模型（免费，复用账号全局 API Key）
DEFAULT_MODELS = [
    {
        "name": "智谱 GLM-4.5 Flash（免费）",
        "provider": "zhipu",
        "model": "glm-4.5-flash",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "api_keys": [],
        "api_key": "",
        "is_default": True,
        "remark": "默认免费模型，密钥留空则复用账号全局 API Key",
        "is_builtin": True,
    },
    {
        "name": "Gemini 3.8 Flash",
        "provider": "gemini",
        "model": "gemini-3.8-flash",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "api_keys": [],
        "api_key": "",
        "is_default": False,
        "remark": "速度快、上下文大；付费档，需填 Google AI Studio API Key，国内需代理",
        "is_builtin": True,
    },
    {
        "name": "Gemini 3.5 Flash-Lite",
        "provider": "gemini",
        "model": "gemini-3.5-flash-lite",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "api_keys": [],
        "api_key": "",
        "is_default": False,
        "remark": "轻量省额度，免费层有每日限额；需填 Google AI Studio API Key，国内需代理",
        "is_builtin": True,
    },
    {
        "name": "Gemini 3.1 Flash-Lite",
        "provider": "gemini",
        "model": "gemini-3.1-flash-lite",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "api_keys": [],
        "api_key": "",
        "is_default": False,
        "remark": "轻量省额度，免费层有每日限额；需填 Google AI Studio API Key，国内需代理",
        "is_builtin": True,
    },
]


# 内置文生图预设（model_type=image；智谱 Key 留空复用账号全局密钥）
DEFAULT_IMAGE_MODELS = [
    {
        "name": "智谱 CogView-3 Flash（免费文生图）",
        "provider": "zhipu",
        "model_type": "image",
        "model": "cogview-3-flash",
        "models": ["cogview-3-flash", "glm-image"],
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "api_keys": [],
        "api_key": "",
        "is_default": True,
        "remark": "cogview-3-flash 免费；glm-image 为高清付费档。密钥留空则复用账号全局 API Key",
        "is_builtin": True,
    },
]


def _type_filter(model_type: str = "") -> dict:
    """默认模型全局唯一：置默认前清空所有其他模型的默认标记（不再按对话/文生图分套）。"""
    return {}


def seed():
    """首次运行按供应商去重，补插内置默认模型（同供应商已有记录则不重复补插）。
    由 main.py lifespan 启动时调用（router.on_event 在 lifespan 应用下不会执行）。"""
    for m in DEFAULT_MODELS:
        if not db.llm_models.find_one({"provider": m["provider"]}):
            doc = {**m, "created_at": datetime.now()}
            db.llm_models.insert_one(doc)
    # 文生图预设：按名称去重补插
    if not db.llm_models.find_one({"name": DEFAULT_IMAGE_MODELS[0]["name"]}):
        for m in DEFAULT_IMAGE_MODELS:
            db.llm_models.insert_one({**m, "created_at": datetime.now()})


def _normalize_keys(body: dict) -> dict:
    """规范化多 Key 字段：兼容旧单字段 api_key，统一存 api_keys 列表。"""
    keys = body.get("api_keys")
    if isinstance(keys, str):
        keys = [k.strip() for k in keys.splitlines() if k.strip()]
    if not isinstance(keys, list):
        keys = []
    keys = [str(k).strip() for k in keys if str(k).strip()]
    if not keys and body.get("api_key"):
        keys = [str(body["api_key"]).strip()]
    body["api_keys"] = keys
    body["api_key"] = keys[0] if keys else ""
    return body


def _normalize_models(body: dict) -> dict:
    """规范化模型 ID 字段：一行一个，统一存 models 列表；model 回填首个以兼容旧读取。"""
    models = body.get("models")
    if isinstance(models, str):
        models = [m.strip() for m in models.splitlines() if m.strip()]
    if not isinstance(models, list):
        models = []
    models = [str(m).strip() for m in models if str(m).strip()]
    if not models and body.get("model"):
        models = [str(body["model"]).strip()]
    body["models"] = models
    body["model"] = models[0] if models else ""
    return body


def _normalize_thinking(body: dict) -> dict:
    """思考档位：auto（按模型能力表）/ disabled / low / high；其它值一律按 auto。"""
    if "thinking_mode" in body or "_id" not in body:
        mode = str(body.get("thinking_mode") or "auto").strip().lower()
        body["thinking_mode"] = mode if mode in THINKING_MODES else "auto"
    return body


@router.get("")
def list_models():
    rows = list(db.llm_models.find().sort("created_at", -1))
    for r in rows:
        r["_id"] = str(r["_id"])
        # 兼容旧记录：供应商兜底智谱；单字段 Key 并入列表
        if not r.get("provider"):
            r["provider"] = "zhipu"
        if not r.get("api_keys") and r.get("api_key"):
            r["api_keys"] = [r["api_key"]]
        elif not r.get("api_keys"):
            r["api_keys"] = []
        if not r.get("models") and r.get("model"):
            r["models"] = [r["model"]]
        elif not r.get("models"):
            r["models"] = []
        r["api_keys"] = [mask_key(k) for k in r["api_keys"]]
        r["api_key"] = r["api_keys"][0] if r["api_keys"] else ""
        r.setdefault("thinking_mode", "auto")
        # 结构化长输出（拆分镜 / 一键提取）不稳的子模型 → 推荐提示（规则在 model_caps.LONG_OUTPUT_ADVICE）
        advice = {m: a for m in r["models"] if (a := model_caps.long_output_advice(
            r.get("base_url") or PROVIDERS.get(r["provider"], {}).get("base_url", ""), m))}
        if advice:
            r["long_output_advice"] = advice
    return {"data": rows, "providers": PROVIDERS,
            "thinking_modes": [{"value": k, "label": v} for k, v in THINKING_MODES.items()]}


@router.post("")
def create_model(body: dict):
    body.setdefault("created_at", datetime.now())
    body.setdefault("is_builtin", False)
    body = _normalize_keys(body)
    body = _normalize_models(body)
    body = _normalize_thinking(body)
    if body.get("is_default"):
        db.llm_models.update_many(_type_filter(), {"$set": {"is_default": False}})
    r = db.llm_models.insert_one(body)
    return {"id": str(r.inserted_id)}


@router.put("/{mid}")
def update_model(mid: str, body: dict):
    body.pop("_id", None)
    if body.get("is_default"):
        db.llm_models.update_many(_type_filter(), {"$set": {"is_default": False}})
    body = _normalize_keys(body)
    if body["api_keys"] and any(KEY_MASK in k for k in body["api_keys"]):
        try:
            old = db.llm_models.find_one({"_id": ObjectId(mid)}) or {}
        except Exception:
            raise HTTPException(status_code=400, detail="无效的模型ID")
        old_keys = old.get("api_keys") or ([old["api_key"]] if old.get("api_key") else [])
        body["api_keys"] = _restore_masked_keys(body["api_keys"], old_keys)
        body["api_key"] = body["api_keys"][0] if body["api_keys"] else ""
    body = _normalize_models(body)
    if "thinking_mode" in body:
        body = _normalize_thinking(body)
    db.llm_models.update_one({"_id": ObjectId(mid)}, {"$set": body})
    return {"ok": True}


@router.delete("/{mid}")
def delete_model(mid: str):
    db.llm_models.delete_one({"_id": ObjectId(mid)})
    return {"ok": True}


@router.post("/{mid}/default")
def set_default(mid: str):
    db.llm_models.update_many(_type_filter(), {"$set": {"is_default": False}})
    db.llm_models.update_one({"_id": ObjectId(mid)}, {"$set": {"is_default": True}})
    return {"ok": True}
