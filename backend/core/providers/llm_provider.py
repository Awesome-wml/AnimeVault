"""智谱GLM大模型服务提供者（OpenAI兼容接口，免费模型glm-4.5-flash）"""
import httpx
import json
import re
import os
import asyncio
import logging
import time
from typing import AsyncIterator, Optional

import threading
from .base import BaseLLMProvider
from . import fake
from . import model_caps

logger = logging.getLogger(__name__)

# 默认使用智谱开放平台，免费模型
DEFAULT_BASE_URL = "https://open.bigmodel.cn/api/paas/v4"
DEFAULT_MODEL = "glm-4.5-flash"

# 结构化（JSON）调用的输出上限：会思考/可思考的模型放宽（思考也占输出额度），其余保持 8192，避免供应商拒绝。
# 智谱 glm-4.5~4.7、glm-5.x 都按 16384（具体上限未公开确认），输出量靠拆分镜分块控制。
_JSON_MAX_TOKENS_DEFAULT = 8192
_JSON_MAX_TOKENS_LONG = 16384


def supports_thinking_switch(base_url: str, model: str) -> bool:
    """兼容旧调用：按模型能力表，这个模型会不会收到 thinking 参数。规则见 model_caps。"""
    return model_caps.supports_thinking_param(base_url, model)


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


class LLMTruncatedError(ValueError):
    """模型输出达到 max_tokens 被截断（finish_reason=length）。原样重试只会再截断一次，调用方应缩短输入。"""

    def __init__(self, chars: int, max_tokens: Optional[int] = None):
        self.chars = chars
        self.max_tokens = max_tokens
        super().__init__(f"模型输出被截断（finish_reason=length，已输出 {chars} 字符，上限 {max_tokens} tokens）")


class LLMRequestError(ValueError):
    """供应商拒绝请求（4xx，非 429）：参数/模型不支持等，重试无意义。带上供应商返回的错误码与原因。"""

    def __init__(self, status: int, code: str = "", message: str = "", model: str = ""):
        self.status, self.code, self.message, self.model = status, str(code or ""), message or "", model
        detail = f"{self.code} {self.message}".strip() or "无错误详情"
        super().__init__(f"模型接口返回 {status}（{detail}）model={model}")


def _error_detail(body) -> tuple:
    """从供应商错误响应体取 (code, message)；兼容 {"error":{code,message}} 与 {"code","msg"}。"""
    if not isinstance(body, dict):
        return "", str(body or "")[:300]
    err = body.get("error", body)
    if isinstance(err, dict):
        return str(err.get("code", "") or ""), str(err.get("message") or err.get("msg") or "")[:300]
    return "", str(err)[:300]


def repair_json_brackets(text: str) -> str:
    """修复结构错误：括号错配（把 ]} 写成 }}、结尾少括号）和元素之间漏逗号
    （“每段占一行”时模型偶尔写成一行一个对象、行间不加逗号）。按字符串外的括号栈纠正。"""
    out, stack = [], []
    in_str = esc = False
    last = ""  # 字符串外上一个非空白字符（字符串结束记为 "）
    pairs = {"{": "}", "[": "]"}
    for ch in text:
        if in_str:
            out.append(ch)
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
                last = '"'
            continue
        if ch in ' \t\r\n':
            out.append(ch)
            continue
        if ch in '{["' and last in ('}', ']', '"') and stack:
            out.append(",")  # 两个元素之间漏了逗号
        if ch == '"':
            in_str = True
        elif ch in pairs:
            stack.append(pairs[ch])
        elif ch in "}]":
            if not stack:
                continue  # 多余的闭括号
            while stack and stack[-1] != ch and ch in stack:
                out.append(stack.pop())  # 先补上漏写的内层闭括号
            if stack and stack[-1] == ch:
                stack.pop()
            else:
                ch = stack.pop()  # 写错了种类：按应有的闭括号算
        out.append(ch)
        last = ch
    out.extend(reversed(stack))
    return "".join(out)


def _strip_broken_tail(text: str) -> str:
    """剥掉尾部写到一半、未闭合的残缺元素，保留前面完整闭合的对象/数组。

    模型中途断流或提前 stop 时，最后一个元素往往只写了一半（字符串未闭合、
    括号未配对）；这半截会把后续括号修复带进字符串状态，导致前面完整的元素也被
    一起作废。这里回退到最后一个完整闭合元素的结束位置，再交括号修复补全外层。
    """
    if not text:
        return text
    stack: list = []
    in_str = esc = False
    last_complete = -1
    for i, ch in enumerate(text):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "{[":
            stack.append(ch)
        elif ch in "}]":
            if stack:
                stack.pop()
            last_complete = i
    if in_str or stack:
        if last_complete >= 0:
            return text[:last_complete + 1]
    return text


def _thinking_of(payload: dict) -> dict:
    return {k: payload[k] for k in model_caps.THINKING_KEYS if k in payload}


# 限流/临时错误状态码：智谱免费模型限流返回 429(1302账户速率/1305模型访问量大)
_RETRY_STATUS_CODES = {429, 500, 502, 503, 504}


class DoubaoLLMProvider(BaseLLMProvider):
    """大模型服务提供者（OpenAI 兼容；原类名保留，避免破坏导入）

    支持传入单个 Key 或 Key 列表；多 Key 时按调用顺序轮询分流，
    遇到限流/重试时自动切换到下一个 Key。
    """

    def __init__(self, api_key, base_url: str = DEFAULT_BASE_URL, model: str = DEFAULT_MODEL,
                 max_retries: int = 5, thinking_mode: Optional[str] = None):
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
        # 模型预设上的手动思考档位：auto/None=按能力表，disabled/low/high=强制
        self.thinking_mode = thinking_mode or "auto"
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
                if 400 <= response.status_code < 500 and response.status_code not in _RETRY_STATUS_CODES:
                    try:
                        code, msg = _error_detail(response.json())
                    except Exception:
                        code, msg = "", response.text[:300]
                    logger.error(f"LLM调用被拒绝 {response.status_code} code={code} message={msg} model={payload.get('model')}")
                    raise LLMRequestError(response.status_code, code, msg, payload.get("model", ""))
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

    async def _stream_chat(self, url: str, payload: dict, meta: Optional[dict] = None) -> AsyncIterator[str]:
        """流式聊天（带基础重试），由调用方迭代驱动，内部自建client

        meta 传入字典时写回结束原因：meta["finish_reason"]（智谱/OpenAI SSE 末块 choices[0].finish_reason，
        length 表示达到 max_tokens 被截断）与 meta["usage"]（有则记）。
        """
        if meta is None:
            meta = {}
        if fake.enabled():
            meta["finish_reason"] = fake.finish_reason(payload.get("messages"))
            for part in fake.chunks(fake.llm_reply(payload.get("messages"))):
                yield part
            return
        async with httpx.AsyncClient(timeout=300.0) as client:
            for attempt in range(self.max_retries):
                headers = self._headers()
                try:
                    async with client.stream("POST", url, headers=headers, json=payload) as response:
                        if response.status_code >= 400:
                            # 流式响应要先读完响应体才能取错误原因（原来直接 .json() 会失败，日志只剩空括号）
                            try:
                                await response.aread()
                                code, msg = _error_detail(response.json())
                            except Exception:
                                code, msg = "", ""
                            err_body = f"{code} {msg}".strip()
                            if 400 <= response.status_code < 500 and response.status_code not in _RETRY_STATUS_CODES:
                                # 参数/模型不支持：重试无意义，带上原因立即失败
                                logger.error(f"LLM流式调用被拒绝 {response.status_code} code={code} message={msg} "
                                             f"model={payload.get('model')} 思考参数={_thinking_of(payload)}")
                                raise LLMRequestError(response.status_code, code, msg, payload.get("model", ""))
                        if response.status_code in _RETRY_STATUS_CODES and attempt < self.max_retries - 1:
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
                                    if data.get("usage"):
                                        meta["usage"] = data["usage"]
                                    if "choices" in data and len(data["choices"]) > 0:
                                        if data["choices"][0].get("finish_reason"):
                                            meta["finish_reason"] = data["choices"][0]["finish_reason"]
                                        delta = data["choices"][0].get("delta", {})
                                        content = delta.get("content", "")
                                        if content:
                                            yield content
                                        finish_reason = data["choices"][0].get("finish_reason")
                                        if finish_reason:
                                            logger.info(f"[LLM] finish_reason={finish_reason}")
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
        meta: Optional[dict] = None,
        on_progress=None,
    ) -> str:
        """以 SSE 流式拉取并在后端内部累积完整文本，避免长响应整段等待导致超时/截断。

        meta 传入字典时写回 finish_reason / usage / chars，供调用方判断是否被截断。
        """
        if meta is None:
            meta = {}
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
        # 思考参数统一由模型能力表决定（预设上的手动档位优先）；不支持的模型不传
        payload.update(model_caps.resolve_thinking(self.base_url, effective_model, thinking, self.thinking_mode))
        logger.info(f"[LLM] 开始流式调用: url={url} model={effective_model} 消息数={len(messages)} "
                    f"思考参数={_thinking_of(payload)}")
        started = time.monotonic()
        degraded = 0
        while True:
            parts: list = []
            total = 0
            last_log = 0
            try:
                async for chunk in self._stream_chat(url, payload, meta):
                    parts.append(chunk)
                    total += len(chunk)
                    # 每累计约 300 字符输出一条进度日志，便于观察流式是否在推进
                    if total - last_log >= 300:
                        logger.debug(f"[LLM] 流式接收中: 已收 {total} 字符")
                        last_log = total
                    if on_progress is not None:
                        try:
                            await on_progress(total)
                        except Exception:
                            pass
                break
            except LLMRequestError as e:
                # 4xx：只为思考参数降级重试（最多两步：disabled → low → 不传），不走退避
                retry, new_fragment = model_caps.next_thinking_after_error(
                    self.base_url, effective_model, _thinking_of(payload), e.status, e.code, e.message)
                if not retry or degraded >= 2:
                    raise
                degraded += 1
                for k in model_caps.THINKING_KEYS:
                    payload.pop(k, None)
                payload.update(new_fragment)
        result_text = "".join(parts)
        meta["chars"] = len(result_text)
        usage = meta.get("usage") or {}
        logger.info(f"[LLM] 流式响应收束: 共 {len(result_text)} 字符, finish_reason={meta.get('finish_reason')}, "
                    f"输出 tokens={usage.get('completion_tokens', '?')}, max_tokens={max_tokens}, "
                    f"耗时 {time.monotonic() - started:.1f}s")
        if not result_text:
            logger.warning("[LLM] 空响应：服务端返回 200 但未产出任何内容（可能限流/审核/超时），将按重试处理")
        return result_text

    async def chat_json(
        self,
        messages: list,
        model: Optional[str] = None,
        max_retries: int = 3,
        thinking: Optional[bool] = False,
        max_tokens: Optional[int] = None,
        on_progress=None,
    ) -> dict:
        """聊天接口（强制JSON输出，带重试；底层流式累积完整响应后解析）

        结构化调用默认不要思考：可关的模型传 disabled，始终思考的模型传 low，不认 thinking 的模型不传
        （model_caps），既省时间也避免思考占用输出额度导致截断。
        max_tokens：调用方按预期输出量给的上限（如拆分镜按小说块字数），模型复读跑飞时早点截断、快速失败；
        不传按模型能力取默认上限。要思考的（low/high/enabled）额外留 4096 给思考，都不超过 16384。
        """
        # 添加系统提示，强制JSON输出
        system_msg = {
            "role": "system",
            "content": "你必须严格按照要求的JSON格式输出，不要有任何额外的解释、markdown标记或其他文字。"
        }

        if messages[0]["role"] != "system":
            messages.insert(0, system_msg)

        for attempt in range(max_retries):
            result = ""
            try:
                logger.info(f"[LLM] chat_json 第 {attempt + 1}/{max_retries} 次尝试")
                effective_model = model or self.model
                # 按静态能力放宽（运行时降级不影响额度）：可思考/始终思考的模型思考也占输出额度
                cap_tokens = (_JSON_MAX_TOKENS_LONG
                              if model_caps.static_capability(self.base_url, effective_model) != model_caps.NONE
                              else _JSON_MAX_TOKENS_DEFAULT)
                limit = cap_tokens
                if max_tokens:
                    fragment = model_caps.resolve_thinking(self.base_url, effective_model, thinking, self.thinking_mode)
                    extra = 4096 if model_caps.thinks(fragment) else 0
                    limit = min(int(max_tokens) + extra, cap_tokens)
                meta: dict = {}
                result = await self._collect_stream(messages, model, temperature=0.3,
                                                    max_tokens=limit, thinking=thinking, meta=meta,
                                                    on_progress=on_progress)
                if meta.get("finish_reason") == "length":
                    # 输出到上限被截断：同样的输入重试只会再截断一次（每次几分钟），直接交给调用方缩短输入
                    logger.warning(f"[LLM] 输出被截断（finish_reason=length，{len(result)} 字符，"
                                   f"max_tokens={limit}），不再原样重试")
                    raise LLMTruncatedError(len(result), limit)

                parsed = self._parse_json_lenient(result)
                logger.info(f"[LLM] JSON 解析成功, 顶层字段: {list(parsed.keys()) if isinstance(parsed, dict) else type(parsed).__name__}")
                return parsed

            except (LLMTruncatedError, LLMRequestError):
                raise  # 截断 / 请求被拒（4xx）：原样重试没有意义

            except json.JSONDecodeError as e:
                raw = (result or "")[:600]
                logger.warning(f"JSON解析失败 (尝试 {attempt + 1}/{max_retries}): {str(e)}")
                logger.warning(f"模型原始响应片段: {raw}")

                if attempt == max_retries - 1:
                    try:
                        bad_path = os.path.join(os.path.dirname(__file__), "..", "..", "_last_bad_raw.txt")
                        with open(bad_path, "w", encoding="utf-8") as f:
                            f.write(result or "")
                        logger.warning(f"完整原始响应已落盘: {bad_path}")
                    except Exception:
                        pass
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
                frag = _strip_broken_tail(m.group(0))
                if len(frag) < len(m.group(0)):
                    logger.warning("[LLM] 响应尾部存在未闭合残缺元素，已截断丢弃，保留前面完整内容")
                fixed = repair_json_quotes(frag)
                for candidate in (frag, repair_json_brackets(frag), fixed, repair_json_brackets(fixed)):
                    try:
                        parsed = json.loads(candidate)
                    except json.JSONDecodeError:
                        continue
                    if candidate is not frag:
                        logger.warning("[LLM] JSON 含未转义双引号或括号错配，已自动修复后解析")
                    return parsed

        raise json.JSONDecodeError("未能从响应中抽取有效 JSON", raw, 0)
