"""LLM 提供者与提示词的统一工厂

支持在提取/生成时按「模型预设 ID」覆盖默认模型配置，
按「提示词 ID」覆盖内置模板；未传则回退用户全局配置 / 类型默认提示词。
"""
import logging
import os
from pymongo import MongoClient
from bson import ObjectId

from fastapi import HTTPException

from core.providers.llm_provider import DoubaoLLMProvider, DEFAULT_BASE_URL, DEFAULT_MODEL
from core.prompt_store import get_prompt

logger = logging.getLogger(__name__)

_client = MongoClient(os.environ.get("MONGO_URL", "mongodb://admin:dongai_mongo_2024@localhost:27017/"))
_db = _client.dongai


def _get_model_preset(model_id: str):
    if not model_id:
        return None
    try:
        return _db.llm_models.find_one({"_id": ObjectId(model_id)})
    except Exception:
        return None


def _preset_keys(preset: dict, user: dict) -> list:
    """从预设取多 Key 列表；兼容旧的单字段 api_key。

    仅内置/智谱预设在未填 Key 时回退用户全局密钥；
    其他供应商（DeepSeek/OpenAI/Gemini 等）Key 不通用，留空则不回退。
    """
    keys = preset.get("api_keys")
    if isinstance(keys, list):
        keys = [str(k).strip() for k in keys if k and str(k).strip()]
    elif preset.get("api_key"):
        keys = [str(preset["api_key"]).strip()]
    else:
        keys = []
    if not keys and preset.get("provider") in (None, "", "zhipu"):
        g = user.get("doubao_api_key")
        keys = [g] if g else []
    return keys


def build_provider(user: dict, model_id: str = None) -> DoubaoLLMProvider:
    """按模型预设构造 provider。

    - model_id 非空：从 llm_models 取预设；预设未填 Key 时回退用户全局密钥。
    - model_id 为空：沿用用户全局 doubao_api_key / doubao_base_url / doubao_model。
    - 预设可挂多个 Key，provider 内部轮询分流。
    """
    preset = _get_model_preset(model_id) if model_id else None

    if preset:
        api_keys = _preset_keys(preset, user)
        base_url = preset.get("base_url") or user.get("doubao_base_url", DEFAULT_BASE_URL)
        model = preset.get("model") or user.get("doubao_model", DEFAULT_MODEL)
    else:
        g = user.get("doubao_api_key")
        api_keys = [g] if g else []
        base_url = user.get("doubao_base_url", DEFAULT_BASE_URL)
        model = user.get("doubao_model", DEFAULT_MODEL)

    if not api_keys:
        raise HTTPException(
            status_code=400,
            detail="请先配置 API 密钥，或在模型管理中为所选预设填写密钥",
        )

    return DoubaoLLMProvider(api_key=api_keys, base_url=base_url, model=model)


def resolve_prompt(prompt_id: str, default_type: str, fallback: str = "") -> str:
    """按提示词 ID 取自定义内容；为空则取该类型默认，再回退内置模板。"""
    if prompt_id:
        try:
            p = _db.prompts.find_one({"_id": ObjectId(prompt_id)})
            if p and p.get("content"):
                return p["content"]
        except Exception:
            logger.warning("提示词 ID 无效: %s", prompt_id)
    return get_prompt(default_type, fallback)


def safe_format(tpl: str, **kwargs) -> str:
    """安全填充模板：缺占位符或多余占位符时不抛 KeyError。

    优先走 str.format；若模板与字段不匹配，则仅替换已知占位符，
    避免用户自定义提示词缺少 {novel_text} 等字段导致提取崩溃。
    """
    if not tpl:
        return ""
    try:
        return tpl.format(**kwargs)
    except (KeyError, IndexError, ValueError):
        out = tpl
        for k, v in kwargs.items():
            out = out.replace("{" + k + "}", str(v))
        return out
