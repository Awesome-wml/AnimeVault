"""智谱文生图服务提供者（免费模型glm-image / cogview）"""
import httpx
import asyncio
import logging
from typing import Optional

from .base import BaseImageProvider

logger = logging.getLogger(__name__)

# 默认使用智谱开放平台，免费文生图模型
DEFAULT_BASE_URL = "https://open.bigmodel.cn/api/paas/v4"
DEFAULT_MODEL = "glm-image"

# 限流/临时错误状态码
_RETRY_STATUS_CODES = {429, 500, 502, 503, 504}


class DoubaoImageProvider(BaseImageProvider):
    """智谱文生图服务提供者（原类名保留，避免破坏导入）"""

    def __init__(self, api_key: str, base_url: str = DEFAULT_BASE_URL, model: str = DEFAULT_MODEL,
                 max_retries: int = 5):
        self.api_key = api_key
        self.base_url = base_url.rstrip('/')
        self.model = model
        self.max_retries = max_retries
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

    async def generate_image(
        self,
        prompt: str,
        neg_prompt: Optional[str] = None,
        width: int = 1280,
        height: int = 1280,
        model: Optional[str] = None,
        **kwargs
    ) -> bytes:
        """
        生成图片

        Args:
            prompt: 正向提示词
            neg_prompt: 负面提示词（智谱接口不支持负面提示词，忽略）
            width: 图片宽度
            height: 图片高度
            model: 模型名称，默认glm-image

        Returns:
            图片二进制数据
        """
        effective_model = model or self.model
        url = f"{self.base_url}/images/generations"

        payload = {
            "model": effective_model,
            "prompt": prompt,
            "size": f"{width}x{height}",
            "n": 1,
            "watermark_enabled": False
        }

        async with httpx.AsyncClient(timeout=180.0) as client:
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
