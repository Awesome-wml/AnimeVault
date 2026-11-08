"""智谱GLM大模型服务提供者（OpenAI兼容接口，免费模型glm-4.5-flash）"""
import httpx
import json
import re
import asyncio
import logging
from typing import AsyncIterator, Optional

import threading
from .base import BaseLLMProvider
from . import fake

logger = logging.getLogger(__name__)

# 默认使用智谱开放平台，免费模型
DEFAULT_BASE_URL = "https://open.bigmodel.cn/api/paas/v4"
DEFAULT_MODEL = "glm-4.5-flash"

# 智谱 GLM-4.5 及以上支持 thinking 参数（关闭深度思考可大幅缩短结构化输出耗时）
_ZHIPU_HOST_HINTS = ("bigmodel.cn", "z.ai")
_ZHIPU_THINKING_MODEL = re.compile(r"^glm-(4\.[5-9]|[5-9])", re.I)
# 结构化（JSON）调用的输出上限：支持长输出的模型放宽，其余保持 8192，避免供应商拒绝
_JSON_MAX_TOKENS_DEFAULT = 8192
_JSON_MAX_TOKENS_LONG = 16384


def supports_thinking_switch(base_url: str, model: str) -> bool:
    """只有智谱开放平台上的 GLM-4.5+ 才传 thinking 参数，避免影响 Gemini/豆包/DeepSeek 等。"""
    url = (base_url or "").lower()
    return any(h in url for h in _ZHIPU_HOST_HINTS) and bool(_ZHIPU_THINKING_MODEL.match(model or ""))


def repair_json_quotes(text: str) -> str:
    """修复 JSON 字符串值内部未转义的 ASCII 双引号（模型常把中文引号输出成英文引号）。

    逐字扫描：在字符串内部遇到未转义的双引号时，只有其后（跳过空白）紧跟 JSON 结构符
    （: } ] ，或逗号后接下一个键/值）才视为字符串结束；否则当作正文引号，按开/闭交替替换为“”。
    """
    out = []
    in_str = False
    inner_open = True  # 当前字符串内下一个正文引号是开引号还是闭引号
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if not in_str:
            out.append(ch)
            if ch == '"':
                in_str, inner_open = True, True
            i += 1
            continue
        if ch == "\\":
            out.append(text[i:i + 2])
            i += 2
            continue
        if ch == "\n":
            out.append("\\n")
            i += 1
            continue
        if ch == '"':
            j = i + 1
            while j < n and text[j] in " \t\r\n":
                j += 1
            nxt = text[j] if j < n else ""
            closing = nxt in (":", "}", "]", "")
            if nxt == ",":
                k = j + 1
                while k < n and text[k] in " \t\r\n":
                    k += 1
                closing = k >= n or text[k] in '"{[-0123456789tfn]}'
            if closing:
                out.append(ch)
                in_str = False
            else:
                out.append("“" if inner_open else "”")
                inner_open = not inner_open
            i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


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
        stream: bool = False,
        max_tokens: Optional[int] = None
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
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens

        if stream:
            # 流式：由 generator 内部管理 client 生命周期，避免 client 在迭代前被关闭
            return self._stream_chat(url, payload)

        async with httpx.AsyncClient(timeout=300.0) as client:
            return await self._chat_with_retry(client, url, payload)

    async def _chat_with_retry(self, client: httpx.AsyncClient, url: str, payload: dict) -> str:
        """非流式调用，带重试与退避；重试时轮换 Key"""
        if fake.enabled():
            return fake.llm_reply(payload.get("messages"))
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
                logger.warning(
                    f"LLM网络异常 [{type(e).__name__}] url={url} model={payload.get('model')}: "
                    f"{e} | cause={e.__cause__}"
                )
                self._rotate_key()
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(min(2 ** attempt * 2, 15))
                    continue
                raise e
        raise ValueError("达到最大重试次数")

    async def _stream_chat(self, url: str, payload: dict) -> AsyncIterator[str]:
        """流式聊天（带基础重试），由调用方迭代驱动，内部自建client"""
        if fake.enabled():
            for part in fake.chunks(fake.llm_reply(payload.get("messages"))):
                yield part
            return
        async with httpx.AsyncClient(timeout=300.0) as client:
            for attempt in range(self.max_retries):
                headers = self._headers()
                try:
                    async with client.stream("POST", url, headers=headers, json=payload) as response:
                        if response.status_code in _RETRY_STATUS_CODES and attempt < self.max_retries - 1:
                            err_body = ""
                            try:
                                rb = response.json()
                                err = rb.get("error", {})
                                if isinstance(err, dict):
                                    err_body = f"{err.get('code', '')} {err.get('message', '')}"
                                else:
                                    err_body = str(err)
                            except Exception:
                                pass
                            logger.warning(f"LLM流式返回 {response.status_code} ({err_body}), 尝试 {attempt + 1}/{self.max_retries}")
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
                    logger.warning(
                        f"LLM流式调用异常 [{type(e).__name__}] url={url} model={payload.get('model')}: "
                        f"{e} | cause={e.__cause__}"
                    )
                    self._rotate_key()
                    if attempt < self.max_retries - 1:
                        await asyncio.sleep(min(2 ** attempt * 2, 15))
                        continue
                    raise e
        raise ValueError("达到最大重试次数")

    async def _collect_stream(
        self,
        messages: list,
        model: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: Optional[int] = 8192,
        thinking: Optional[bool] = None,
    ) -> str:
        """以 SSE 流式拉取并在后端内部累积完整文本，避免长响应整段等待导致超时/截断。"""
        url = f"{self.base_url}/chat/completions"
        effective_model = model or self.model
        payload: dict = {
            "model": effective_model,
            "messages": messages,
            "temperature": temperature,
            "stream": True,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        # thinking=None 不传参数（供应商默认）；True/False 仅对支持的模型生效
        if thinking is not None and supports_thinking_switch(self.base_url, effective_model):
            payload["thinking"] = {"type": "enabled" if thinking else "disabled"}
        parts: list = []
        logger.info(f"[LLM] 开始流式调用: url={url} model={effective_model} 消息数={len(messages)}")
        async for chunk in self._stream_chat(url, payload):
            parts.append(chunk)
        result_text = "".join(parts)
        logger.info(f"[LLM] 流式响应收束: 共 {len(result_text)} 字符")
        return result_text

    async def chat_json(
        self,
        messages: list,
        model: Optional[str] = None,
        max_retries: int = 3,
        thinking: Optional[bool] = False,
    ) -> dict:
        """聊天接口（强制JSON输出，带重试；底层流式累积完整响应后解析）

        结构化调用默认关闭深度思考（仅智谱 GLM-4.5+ 生效），既省时间也避免思考占用输出额度导致截断。
        """
        # 添加系统提示，强制JSON输出
        system_msg = {
            "role": "system",
            "content": "你必须严格按照要求的JSON格式输出，不要有任何额外的解释、markdown标记或其他文字。"
        }

        if messages[0]["role"] != "system":
            messages.insert(0, system_msg)

        for attempt in range(max_retries):
            try:
                logger.info(f"[LLM] chat_json 第 {attempt + 1}/{max_retries} 次尝试")
                effective_model = model or self.model
                max_tokens = (_JSON_MAX_TOKENS_LONG if supports_thinking_switch(self.base_url, effective_model)
                              else _JSON_MAX_TOKENS_DEFAULT)
                result = await self._collect_stream(messages, model, temperature=0.3,
                                                    max_tokens=max_tokens, thinking=thinking)

                parsed = self._parse_json_lenient(result)
                logger.info(f"[LLM] JSON 解析成功, 顶层字段: {list(parsed.keys()) if isinstance(parsed, dict) else type(parsed).__name__}")
                return parsed

            except json.JSONDecodeError as e:
                raw = (result or "")[:600]
                logger.warning(f"JSON解析失败 (尝试 {attempt + 1}/{max_retries}): {str(e)}")
                logger.warning(f"模型原始响应片段: {raw}")

                if attempt == max_retries - 1:
                    raise ValueError(f"多次尝试后仍无法解析JSON响应: {str(e)}")

            except Exception as e:
                logger.error(f"LLM调用失败 (尝试 {attempt + 1}/{max_retries}): {str(e)}")
                if attempt == max_retries - 1:
                    raise

        raise ValueError("达到最大重试次数")

    @staticmethod
    def _parse_json_lenient(text: str) -> dict:
        """容错解析模型返回：去 markdown 包裹，必要时从前后缀文字中抽取 JSON 片段。"""
        if text is None:
            raise json.JSONDecodeError("空响应", "", 0)
        raw = text.strip()
        # 去掉 markdown 代码块包裹
        if raw.startswith("```json"):
            raw = raw[7:]
        elif raw.startswith("```"):
            raw = raw[3:]
        if raw.endswith("```"):
            raw = raw[:-3]
        raw = raw.strip()

        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass

        # 从文字前后缀中抽取对象 / 数组片段；失败再修复字符串内未转义的双引号
        for pattern in (r"\{.*\}", r"\[.*\]"):
            m = re.search(pattern, raw, re.S)
            if m:
                frag = m.group(0)
                for candidate in (frag, repair_json_quotes(frag)):
                    try:
                        parsed = json.loads(candidate)
                    except json.JSONDecodeError:
                        continue
                    if candidate is not frag:
                        logger.warning("[LLM] JSON 含未转义双引号，已自动修复后解析")
                    return parsed

        raise json.JSONDecodeError("未能从响应中抽取有效 JSON", raw, 0)
