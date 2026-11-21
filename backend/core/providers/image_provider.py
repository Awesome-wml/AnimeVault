"""文生图服务提供者：智谱（cogview / glm-image）与火山方舟 Seedream（可带资产参考图），接口都是 /images/generations"""
import httpx
import asyncio
import logging
import re
from typing import List, Optional

from .base import BaseImageProvider
from . import fake

logger = logging.getLogger(__name__)

# 默认使用智谱开放平台，免费文生图模型
DEFAULT_BASE_URL = "https://open.bigmodel.cn/api/paas/v4"
DEFAULT_MODEL = "cogview-3-flash"

# 限流/临时错误状态码
_RETRY_STATUS_CODES = {429, 500, 502, 503, 504}


def is_glm_image(model: Optional[str]) -> bool:
    """是否为 glm-image（付费高清档，尺寸按 32 倍数推荐档）。"""
    return (model or "").strip().lower() == "glm-image"


def image_size(model: Optional[str], orientation: str = "landscape") -> tuple:
    """按模型返回合规出图尺寸 (width, height)。

    glm-image / Seedream：1280x1280 / 1728x960 / 960x1728；
    cogview 系列：1024x1024 / 1344x768 / 768x1344。
    orientation: landscape / square / portrait
    """
    # Seedream 5.x 实测接受这三档（总像素约 92 万～261 万之间）；四格图每格 640px，比 1024 档清楚
    glm = is_glm_image(model) or supports_reference_images(model)
    if orientation == "square":
        return (1280, 1280) if glm else (1024, 1024)
    if orientation == "portrait":
        return (960, 1728) if glm else (768, 1344)
    return (1728, 960) if glm else (1344, 768)


# 出图模型的名字特征：预设没标类型时据此判断它是“对话”还是“出图”（设置 → 模型里可以手动改）
_IMAGE_MODEL_RE = re.compile(r"seedream|seededit|cogview|dall-?e|imagen|flux|stable-diffusion|sdxl|(^|[-_/])image($|[-_/\d])", re.I)
MODEL_TYPES = {"chat": "对话", "image": "出图"}


def is_image_model(model: Optional[str]) -> bool:
    return bool(_IMAGE_MODEL_RE.search((model or "").strip()))


def preset_models(preset: Optional[dict]) -> list:
    preset = preset or {}
    return list(preset.get("models") or ([preset["model"]] if preset.get("model") else []))


def model_kind(preset: Optional[dict], model: Optional[str]) -> str:
    """预设里这个模型的用途：chat（写小说 / 转剧本 / 提取 / 拆分镜）或 image（资产图 / 四格图）。
    预设上手动标了用途的，整条预设都按手动的算；没标（自动）的按模型名判断——
    所以一条预设里可以同时放对话模型和出图模型，各归各的。"""
    t = str((preset or {}).get("model_type") or "").strip().lower()
    if t in MODEL_TYPES:
        return t
    return "image" if is_image_model(model) else "chat"


def preset_kinds(preset: Optional[dict]) -> set:
    """这条预设能干哪几类活。没有模型 ID 的空预设算对话。"""
    return {model_kind(preset, m) for m in preset_models(preset)} or {model_kind(preset, None)}


def models_of_kind(preset: Optional[dict], kind: str) -> list:
    return [m for m in preset_models(preset) if model_kind(preset, m) == kind]


MAX_REFERENCE_IMAGES = 6     # 一次最多带几张参考图（角色 → 场景 → 道具，按绑定顺序取前几张）
_REFERENCE_MODEL_MARKS = ("seedream", "seededit")   # 接受参考图的出图模型（火山方舟 Seedream 系列）


def supports_reference_images(model: Optional[str]) -> bool:
    """这个出图模型收不收参考图。收的：画面照着资产图画；不收的（glm-image / cogview）：只能靠文字设定。"""
    m = (model or "").strip().lower()
    return any(mark in m for mark in _REFERENCE_MODEL_MARKS)


REFERENCE_MAX_BYTES = 1_500_000   # 参考图超过这么大就先缩小再传：6 张原图直接 base64 请求体会有几十 MB
REFERENCE_MAX_EDGE = 1536


def _shrink(raw: bytes) -> Optional[bytes]:
    """把大图缩到长边 REFERENCE_MAX_EDGE 的 JPEG；不是图片或处理失败返回 None（调用方原样传）。"""
    try:
        import io
        from PIL import Image
        img = Image.open(io.BytesIO(raw)).convert("RGB")
        img.thumbnail((REFERENCE_MAX_EDGE, REFERENCE_MAX_EDGE))
        out = io.BytesIO()
        img.save(out, format="JPEG", quality=90)
        return out.getvalue()
    except Exception:
        return None


def _data_uri(path: str) -> Optional[str]:
    import base64
    from pathlib import Path
    f = Path(path)
    if not f.exists():
        return None
    ext = f.suffix.lower().lstrip(".") or "png"
    ext = "jpeg" if ext == "jpg" else ext
    raw = f.read_bytes()
    if len(raw) > REFERENCE_MAX_BYTES:
        small = _shrink(raw)
        if small:
            raw, ext = small, "jpeg"
    return f"data:image/{ext};base64," + base64.b64encode(raw).decode("ascii")


class DoubaoImageProvider(BaseImageProvider):
    """智谱文生图服务提供者（原类名保留，避免破坏导入）"""

    def __init__(self, api_key: str, base_url: str = DEFAULT_BASE_URL, model: str = DEFAULT_MODEL,
                 max_retries: int = 5):
        self.api_key = api_key
        self.base_url = base_url.rstrip('/')
        self.model = model
        self.max_retries = max_retries
        self.source = ""   # 这个模型是怎么选出来的（页面选的预设 / 默认出图预设 / 账号设置），由工厂填，出图日志里带上
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

    async def generate_image(
        self,
        prompt: str,
        neg_prompt: Optional[str] = None,
        width: int = 1024,
        height: int = 1024,
        model: Optional[str] = None,
        reference_images: Optional[List[str]] = None,
        **kwargs
    ) -> bytes:
        """
        生成图片

        Args:
            prompt: 正向提示词
            neg_prompt: 负面提示词（智谱接口不支持负面提示词，忽略）
            width: 图片宽度
            height: 图片高度
            model: 模型名称，默认 cogview-3-flash
            reference_images: 参考图本地路径（角色形态图、场景图、道具图）。glm-image / cogview 的
                images/generations 接口不接受参考图，这里只记日志、不上传；换成支持多图参考的模型时
                在这里接上，调用方（四格分镜出图）已经按顺序传进来。

        Returns:
            图片二进制数据
        """
        if fake.enabled():
            return fake.image_bytes()
        effective_model = model or self.model
        url = f"{self.base_url}/images/generations"

        payload = {
            "model": effective_model,
            "prompt": prompt,
            "size": f"{width}x{height}",
            "n": 1,
            "watermark_enabled": False
        }
        if supports_reference_images(effective_model):
            # Seedream（火山方舟，doubao-seedream-5-5 实测）：关水印的参数叫 watermark，不认智谱的 watermark_enabled
            # ——不传 watermark 时图的右下角会带“AI生成”水印，带不带参考图都要传
            payload.pop("watermark_enabled", None)
            payload.update({"watermark": False, "response_format": "url"})
            # 参考图放 image 字段（data URI 列表），画面照着资产图画。万一接口拒绝（4xx），
            # 下面会去掉参考图重试一次并记日志，不让出图整个失败
            uris = [u for u in (_data_uri(p) for p in (reference_images or [])[:MAX_REFERENCE_IMAGES]) if u]
            if uris:
                payload["image"] = uris
                logger.info(f"文生图 {effective_model} 带 {len(uris)} 张资产参考图")
        elif reference_images:
            logger.info(f"文生图模型 {effective_model} 不支持参考图，忽略 {len(reference_images)} 张；资产设定已写进提示词")

        logger.info(f"文生图请求: 模型={effective_model} 尺寸={width}x{height} 地址={url} 来源={self.source or '未标明'}")
        async with httpx.AsyncClient(timeout=300.0) as client:  # Seedream 带参考图实测 70～80 秒一张
            for attempt in range(self.max_retries):
                try:
                    response = await client.post(url, headers=self.headers, json=payload)
                    if response.status_code in _RETRY_STATUS_CODES and attempt < self.max_retries - 1:
                        error_body = ""
                        try:
                            error_body = response.json().get("error", {}).get("message", "")
                        except Exception:
                            pass
                        logger.warning(f"文生图返回 {response.status_code} ({error_body}), 尝试 {attempt + 1}/{self.max_retries}")
                        await asyncio.sleep(min(2 ** attempt * 3, 30))
                        continue
                    response.raise_for_status()
                    result = response.json()

                    # 获取图片URL
                    if "data" not in result or len(result["data"]) == 0:
                        raise ValueError("生成接口未返回图片数据")
                    image_url = result["data"][0].get("url")
                    if not image_url:
                        raise ValueError("生成接口未返回图片URL")

                    # 下载图片
                    img_response = await client.get(image_url)
                    img_response.raise_for_status()
                    return img_response.content

                except httpx.HTTPStatusError as e:
                    logger.error(f"文生图API调用失败: {e.response.text}")
                    if "image" in payload and 400 <= e.response.status_code < 500 and e.response.status_code != 429:
                        logger.warning("带参考图的请求被拒，去掉参考图重试（本次画面只靠文字设定）")
                        payload.pop("image", None)
                        continue
                    if attempt < self.max_retries - 1:
                        await asyncio.sleep(min(2 ** attempt * 3, 30))
                        continue
                    raise ValueError(f"文生图失败: {e.response.text}")
                except (httpx.TimeoutException, httpx.NetworkError) as e:
                    logger.warning(f"文生图网络异常: {str(e)}, 尝试 {attempt + 1}/{self.max_retries}")
                    if attempt < self.max_retries - 1:
                        await asyncio.sleep(min(2 ** attempt * 2, 15))
                        continue
                    raise ValueError(f"文生图网络异常: {str(e)}")

        raise ValueError("达到最大重试次数")
