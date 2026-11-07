"""智谱GLM大模型服务提供者（OpenAI兼容接口，免费模型glm-4.7-flash）"""
import httpx
import json
import asyncio
import logging
from typing import AsyncIterator, Optional

import threading
from .base import BaseLLMProvider

logger = logging.getLogger(__name__)

# 默认使用智谱开放平台，免费模型
DEFAULT_BASE_URL = "https://open.bigmodel.cn/api/paas/v4"
DEFAULT_MODEL = "glm-4.7-flash"

# 限流/临时错误状态码：智谱免费模型限流返回 429(1302账户速率/1305模型访问量大)
_RETRY_STATUS_CODES = {429, 500, 502, 503, 504}


class DoubaoLLMProvider(BaseLLMProvider):
    """大模型服务提供者（OpenAI 兼容；原类名保留，避免破坏导入）

    支持传入单个 Key 或 Key 列表；多 Key 时按调用顺序轮询分流，
    遇到限流/重试时自动切换到下一个 Key。
    """

    def __init__(self, api_key, base_url: str = DEFAULT_BASE_URL, model: str = DEFAULT_MODEL,
                 max_retries: int = 5):
        # 归一化为 Key 列表
        if isinstance(api_key, (list, tuple)):
            keys = [str(k).strip() for k in api_key if k and str(k).strip()]
        elif api_key:
            keys = [str(api_key).strip()]
        else:
            keys = []
        self.api_keys = keys
        self.api_key = keys[0] if keys else ""
        self.base_url = base_url.rstrip('/')
        self.model = model
        self.max_retries = max_retries
        self._key_idx = 0
        self._lock = threading.Lock()

    def _headers(self) -> dict:
        if not self.api_keys:
            return {"Content-Type": "application/json"}
        key = self.api_keys[self._key_idx % len(self.api_keys)]
        return {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json"
        }

    def _rotate_key(self):
        """切换到下一个 Key（仅多 Key 时生效）"""
        if len(self.api_keys) > 1:
            with self._lock:
                self._key_idx = (self._key_idx + 1) % len(self.api_keys)

    async def chat(
        self,
        messages: list,
        model: Optional[str] = None,
        temperature: float = 0.7,
        stream: bool = False
    ) -> str | AsyncIterator[str]:
        """聊天接口（带429限流自动退避重试）"""
        url = f"{self.base_url}/chat/completions"
        effective_model = model or self.model
        payload = {
            "model": effective_model,
            "messages": messages,
            "temperature": temperature,
            "stream": stream
        }

        if stream:
            # 流式：由 generator 内部管理 client 生命周期，避免 client 在迭代前被关闭
            return self._stream_chat(url, payload)

        async with httpx.AsyncClient(timeout=300.0) as client:
            return await self._chat_with_retry(client, url, payload)

    async def _chat_with_retry(self, client: httpx.AsyncClient, url: str, payload: dict) -> str:
        """非流式调用，带重试与退避；重试时轮换 Key"""
        for attempt in range(self.max_retries):
            headers = self._headers()
            try:
                response = await client.post(url, headers=headers, json=payload)
                # 限流或临时错误：退避重试
                if response.status_code in _RETRY_STATUS_CODES:
                    error_body = ""
                    try:
                        error_body = response.json().get("error", {}).get("message", "")
                    except Exception:
                        pass
                    logger.warning(f"LLM调用返回 {response.status_code} ({error_body}), 尝试 {attempt + 1}/{self.max_retries}")
                    self._rotate_key()
                    if attempt < self.max_retries - 1:
                        await asyncio.sleep(min(2 ** attempt * 3, 30))  # 3s,6s,12s,24s,30s 退避
                        continue
                response.raise_for_status()
                result = response.json()
                return result["choices"][0]["message"]["content"]
            except httpx.HTTPStatusError as e:
                self._rotate_key()
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(min(2 ** attempt * 3, 30))
                    continue
                raise e
            except (httpx.TimeoutException, httpx.NetworkError) as e:
                logger.warning(f"LLM网络异常: {str(e)}, 尝试 {attempt + 1}/{self.max_retries}")
                self._rotate_key()
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(min(2 ** attempt * 2, 15))
                    continue
                raise e
        raise ValueError("达到最大重试次数")

    async def _stream_chat(self, url: str, payload: dict) -> AsyncIterator[str]:
        """流式聊天（带基础重试），由调用方迭代驱动，内部自建client"""
        async with httpx.AsyncClient(timeout=300.0) as client:
            for attempt in range(self.max_retries):
                headers = self._headers()
                try:
                    async with client.stream("POST", url, headers=headers, json=payload) as response:
                        if response.status_code in _RETRY_STATUS_CODES and attempt < self.max_retries - 1:
                            self._rotate_key()
                            await asyncio.sleep(min(2 ** attempt * 3, 30))
                            continue
                        response.raise_for_status()
                        async for line in response.aiter_lines():
                            if line.startswith("data: "):
                                data_str = line[6:]
                                if data_str.strip() == "[DONE]":
                                    break
                                try:
                                    data = json.loads(data_str)
                                    if "choices" in data and len(data["choices"]) > 0:
                                        delta = data["choices"][0].get("delta", {})
                                        content = delta.get("content", "")
                                        if content:
                                            yield content
                                except json.JSONDecodeError:
                                    continue
                        return  # 正常流结束
                except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError) as e:
                    logger.warning(f"LLM流式调用异常: {str(e)}, 尝试 {attempt + 1}/{self.max_retries}")
                    self._rotate_key()
                    if attempt < self.max_retries - 1:
                        await asyncio.sleep(min(2 ** attempt * 2, 15))
                        continue
                    raise e
        raise ValueError("达到最大重试次数")

    async def chat_json(
        self,
        messages: list,
        model: Optional[str] = None,
        max_retries: int = 3
    ) -> dict:
        """聊天接口（强制JSON输出，带重试）"""
        # 添加系统提示，强制JSON输出
        system_msg = {
            "role": "system",
            "content": "你必须严格按照要求的JSON格式输出，不要有任何额外的解释、markdown标记或其他文字。"
        }

        if messages[0]["role"] != "system":
            messages.insert(0, system_msg)

        for attempt in range(max_retries):
            try:
                result = await self.chat(messages, model, temperature=0.3, stream=False)

                # 清理可能的markdown代码块标记
                result = result.strip()
                if result.startswith("```json"):
                    result = result[7:]
                if result.startswith("```"):
                    result = result[3:]
                if result.endswith("```"):
                    result = result[:-3]
                result = result.strip()

                # 解析JSON
                parsed = json.loads(result)
                return parsed

            except json.JSONDecodeError as e:
                logger.warning(f"JSON解析失败 (尝试 {attempt + 1}/{max_retries}): {str(e)}")
                logger.debug(f"原始响应: {result[:500]}")

                if attempt == max_retries - 1:
                    raise ValueError(f"多次尝试后仍无法解析JSON响应: {str(e)}")

            except Exception as e:
                logger.error(f"LLM调用失败 (尝试 {attempt + 1}/{max_retries}): {str(e)}")
                if attempt == max_retries - 1:
                    raise

        raise ValueError("达到最大重试次数")
