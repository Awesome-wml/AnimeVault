"""LLM 模型预设管理 API"""
from fastapi import APIRouter, HTTPException
from db.sync_client import get_sync_db
from bson import ObjectId
from datetime import datetime

from core.providers.model_caps import THINKING_MODES

router = APIRouter(prefix="/api/models", tags=["模型管理"])

db = get_sync_db()

# 供应商及其默认接入地址（OpenAI 兼容接口）
PROVIDERS = {
    "zhipu": {"label": "智谱 GLM", "base_url": "https://open.bigmodel.cn/api/paas/v4"},
    "deepseek": {"label": "DeepSeek", "base_url": "https://api.deepseek.com/v1"},
    "openai": {"label": "OpenAI", "base_url": "https://api.openai.com/v1"},
    "gemini": {"label": "Google Gemini", "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/"},
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


def _type_filter(model_type: str) -> dict:
    """默认模型按类型各自唯一：文生图只和文生图互斥，对话（含无类型旧记录）只和对话互斥。"""
    if model_type == "image":
        return {"model_type": "image"}
    return {"model_type": {"$ne": "image"}}


@router.on_event("startup")
def seed():
    """首次运行按供应商去重，补插内置默认模型（同供应商已有记录则不重复补插）"""
    for m in DEFAULT_MODELS:
        if not db.llm_models.find_one({"provider": m["provider"], "model_type": {"$ne": "image"}}):
            doc = {**m, "created_at": datetime.now()}
            db.llm_models.insert_one(doc)
    # 文生图预设：一个都没有时补插
    if not db.llm_models.find_one({"model_type": "image"}):
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
        r.setdefault("thinking_mode", "auto")
        # 模型类型：chat 对话（默认）/ image 文生图
        if r.get("model_type") not in ("chat", "image"):
            r["model_type"] = "chat"
    return {"data": rows, "providers": PROVIDERS,
            "thinking_modes": [{"value": k, "label": v} for k, v in THINKING_MODES.items()]}


@router.post("")
def create_model(body: dict):
    body.setdefault("created_at", datetime.now())
    body.setdefault("is_builtin", False)
    body.setdefault("model_type", "chat")
    if body.get("model_type") not in ("chat", "image"):
        body["model_type"] = "chat"
    body = _normalize_keys(body)
    body = _normalize_models(body)
    body = _normalize_thinking(body)
    if body.get("is_default"):
        db.llm_models.update_many(_type_filter(body["model_type"]), {"$set": {"is_default": False}})
    r = db.llm_models.insert_one(body)
    return {"id": str(r.inserted_id)}


@router.put("/{mid}")
def update_model(mid: str, body: dict):
    body.pop("_id", None)
    if "model_type" in body and body["model_type"] not in ("chat", "image"):
        body["model_type"] = "chat"
    if body.get("is_default"):
        cur = db.llm_models.find_one({"_id": ObjectId(mid)}) or {}
        mtype = body.get("model_type") or cur.get("model_type") or "chat"
        db.llm_models.update_many(_type_filter(mtype), {"$set": {"is_default": False}})
    body = _normalize_keys(body)
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
    cur = db.llm_models.find_one({"_id": ObjectId(mid)}) or {}
    db.llm_models.update_many(_type_filter(cur.get("model_type") or "chat"), {"$set": {"is_default": False}})
    db.llm_models.update_one({"_id": ObjectId(mid)}, {"$set": {"is_default": True}})
    return {"ok": True}
