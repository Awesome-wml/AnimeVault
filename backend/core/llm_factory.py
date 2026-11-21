"""LLM 提供者与提示词的统一工厂

支持在提取/生成时按「模型预设 ID」覆盖默认模型配置，
按「提示词 ID」覆盖内置模板；未传则回退用户全局配置 / 类型默认提示词。
"""
import logging
from db.sync_client import get_sync_db
from bson import ObjectId

from fastapi import HTTPException

from core.providers.llm_provider import DoubaoLLMProvider, DEFAULT_BASE_URL, DEFAULT_MODEL
from core.providers.image_provider import (
    DoubaoImageProvider,
    DEFAULT_BASE_URL as IMG_DEFAULT_BASE_URL,
    DEFAULT_MODEL as IMG_DEFAULT_MODEL,
    MODEL_TYPES,
    model_kind,
    models_of_kind,
    preset_kinds,
)

logger = logging.getLogger(__name__)

_db = get_sync_db()


def _get_model_preset(model_id: str):
    if not model_id:
        return None
    try:
        return _db.llm_models.find_one({"_id": ObjectId(model_id)})
    except Exception:
        return None


def default_preset(kind: str):
    """这类用途（chat / image）被设为默认的模型预设；没有设过返回 None。
    默认按用途各有一个：对话默认管写小说 / 转剧本 / 提取 / 拆分镜，出图默认管资产图 / 四格图。"""
    for p in _db.llm_models.find({"is_default": True}):
        if kind in preset_kinds(p):
            return p
    return None


def _resolve_preset(model_id: str, model: str, kind: str):
    """按“页面选的预设 → 这类用途的默认预设 → 账号设置”的顺序选模型，并拦住用错类型的。
    返回 (预设或 None, 模型名或 None, 来源说明)；模型名为 None 表示用账号设置里的模型。"""
    if model_id:
        preset = _get_model_preset(model_id)
        if not preset:
            raise HTTPException(status_code=400, detail="所选的模型已被删除，请在页面上重新选择模型")
        name = preset.get("name") or model_id
        chosen = model or next(iter(models_of_kind(preset, kind)), None)
        if not chosen or model_kind(preset, chosen) != kind:
            other = "image" if kind == "chat" else "chat"
            raise HTTPException(
                status_code=400,
                detail=f"「{name}」{'的 ' + model + ' ' if model else ''}是{MODEL_TYPES[other]}模型，"
                       f"这里需要{MODEL_TYPES[kind]}模型。请换一个，或到 设置 → 模型 里改它的用途")
        return preset, chosen, f"页面选的预设「{name}」"
    preset = default_preset(kind)
    if preset:
        return preset, models_of_kind(preset, kind)[0], f"默认{MODEL_TYPES[kind]}预设「{preset.get('name')}」"
    return None, None, "账号设置（没有设默认预设）"


def _no_key_detail(preset, kind_cn: str) -> str:
    """没有可用密钥时说清楚是哪条预设、去哪里填。"""
    if preset:
        return (f"模型「{preset.get('name') or ''}」没有填 API 密钥（这家供应商的密钥和智谱不通用，不会自动借用全局密钥）。"
                f"到 设置 → 模型 里给它填上密钥，或换一个{kind_cn}模型")
    return f"还没有可用的{kind_cn}模型：到 设置 → 模型 里填全局密钥，或新建一个{kind_cn}模型并设为默认"


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


def build_provider(user: dict, model_id: str = None, model: str = None) -> DoubaoLLMProvider:
    """按模型预设构造 provider。

    - model_id 非空：从 llm_models 取预设；预设未填 Key 时回退用户全局密钥。出图预设不能用在这里（直接报错）。
    - model 非空：用指定的具体模型覆盖预设默认模型（三级联动选到子模型时传入）。
    - model_id 为空：用“默认对话预设”；没设过默认才沿用用户全局 doubao_api_key / doubao_base_url / doubao_model。
    - 预设可挂多个 Key，provider 内部轮询分流。
    """
    preset, model, source = _resolve_preset(model_id, model, "chat")

    if preset:
        api_keys = _preset_keys(preset, user)
        base_url = preset.get("base_url") or user.get("doubao_base_url", DEFAULT_BASE_URL)
        models = preset.get("models") or ([preset["model"]] if preset.get("model") else [])
        resolved = models[0] if models else user.get("doubao_model", DEFAULT_MODEL)
    else:
        g = user.get("doubao_api_key")
        api_keys = [g] if g else []
        base_url = user.get("doubao_base_url", DEFAULT_BASE_URL)
        resolved = user.get("doubao_model", DEFAULT_MODEL)

    if not api_keys:
        raise HTTPException(
            status_code=400,
            detail=_no_key_detail(preset, "对话"),
        )

    # 预设上的思考档位（设置 → 模型）：auto=按模型能力表（core/providers/model_caps.py）
    thinking_mode = (preset or {}).get("thinking_mode") or "auto"
    logger.info(f"[模型选择] 文字用 {model or resolved}（{source}）")
    return DoubaoLLMProvider(api_key=api_keys, base_url=base_url, model=model or resolved,
                             thinking_mode=thinking_mode)


def build_image_provider(user: dict, model_id: str = None, model: str = None) -> DoubaoImageProvider:
    """按模型预设构造文生图 provider。

    - model_id 指向一条出图预设；取其 Key / base_url / 默认子模型。对话预设不能用在这里（直接报错）。
    - 预设未填 Key 时，zhipu 回退账号全局密钥；其他供应商不回退。
    - model_id 为空：用“默认出图预设”（设置 → 模型里标了默认的那条出图模型）；
      没设过默认才回退账号 doubao_image_model / 免费模型。
    """
    preset, model, source = _resolve_preset(model_id, model, "image")

    if preset:
        api_keys = _preset_keys(preset, user)
        base_url = preset.get("base_url") or user.get("doubao_base_url", IMG_DEFAULT_BASE_URL)
        models = preset.get("models") or ([preset["model"]] if preset.get("model") else [])
        resolved = models[0] if models else (user.get("doubao_image_model") or IMG_DEFAULT_MODEL)
    else:
        g = user.get("doubao_api_key")
        api_keys = [g] if g else []
        base_url = user.get("doubao_base_url", IMG_DEFAULT_BASE_URL)
        resolved = user.get("doubao_image_model") or IMG_DEFAULT_MODEL

    if not api_keys:
        raise HTTPException(
            status_code=400,
            detail=_no_key_detail(preset, "出图"),
        )

    provider = DoubaoImageProvider(api_key=api_keys[0], base_url=base_url, model=model or resolved)
    provider.source = source
    logger.info(f"[模型选择] 出图用 {provider.model}（{source}）")
    return provider


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
