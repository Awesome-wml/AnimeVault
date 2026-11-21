"""流式输出中途断线不能在流内部从头重试（会把前半截拼两遍）；审核截断、缺结束原因不能当成功。"""
import asyncio

import httpx
import pytest

from core.providers import llm_provider as lp
from core.providers.llm_provider import (DoubaoLLMProvider, LLMContentFilteredError, LLMStreamInterrupted)


class _Resp:
    def __init__(self, lines, fail_after=None):
        self.status_code = 200
        self._lines, self._fail_after = lines, fail_after

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def raise_for_status(self):
        pass

    async def aiter_lines(self):
        for i, ln in enumerate(self._lines):
            if self._fail_after is not None and i == self._fail_after:
                raise httpx.ReadTimeout("boom")
            yield ln


def _sse(text, finish=None):
    import json
    choice = {"delta": {"content": text}}
    if finish:
        choice["finish_reason"] = finish
    return "data: " + json.dumps({"choices": [choice]}, ensure_ascii=False)


@pytest.fixture
def provider(monkeypatch):
    monkeypatch.setattr(lp.fake, "enabled", lambda: False)
    real_sleep = asyncio.sleep

    async def no_sleep(*_a, **_k):
        await real_sleep(0)
    monkeypatch.setattr(lp.asyncio, "sleep", no_sleep)
    return DoubaoLLMProvider(api_key=["k1", "k2"], base_url="https://example.invalid/v4", model="glm-4.6-flash")


def _patch_stream(monkeypatch, responses):
    calls = {"n": 0}

    def stream(self, method, url, headers=None, json=None):
        r = responses[min(calls["n"], len(responses) - 1)]
        calls["n"] += 1
        return r
    monkeypatch.setattr(httpx.AsyncClient, "stream", stream)
    return calls


def test_stream_interrupted_after_output_is_not_restarted(provider, monkeypatch):
    calls = _patch_stream(monkeypatch, [
        _Resp([_sse("前半截"), _sse("后面")], fail_after=1),
        _Resp([_sse("完整输出", "stop")]),
    ])

    async def run():
        got = []
        async for c in provider._stream_chat("u", {"model": "m", "messages": []}, {}):
            got.append(c)
        return got
    with pytest.raises(LLMStreamInterrupted):
        asyncio.run(run())
    assert calls["n"] == 1


def test_stream_retries_when_nothing_yielded(provider, monkeypatch):
    calls = _patch_stream(monkeypatch, [
        _Resp([_sse("x")], fail_after=0),
        _Resp([_sse("完整", "stop")]),
    ])

    async def run():
        meta = {}
        out = [c async for c in provider._stream_chat("u", {"model": "m", "messages": []}, meta)]
        return out, meta
    out, meta = asyncio.run(run())
    assert out == ["完整"] and meta["finish_reason"] == "stop" and calls["n"] == 2


def test_chat_json_whole_retry_after_interruption(provider, monkeypatch):
    _patch_stream(monkeypatch, [
        _Resp([_sse('{"segments":[{"a":1},'), _sse('{"b":2}]}')], fail_after=1),
        _Resp([_sse('{"segments":[{"a":1}]}', "stop")]),
    ])
    got = asyncio.run(provider.chat_json([{"role": "user", "content": "x"}]))
    assert got == {"segments": [{"a": 1}]}


def test_chat_json_content_filter_raises(provider, monkeypatch):
    _patch_stream(monkeypatch, [_Resp([_sse('{"segments":[{"a":1},{"b"', "sensitive")])])
    with pytest.raises(LLMContentFilteredError):
        asyncio.run(provider.chat_json([{"role": "user", "content": "x"}]))


def test_transport_retries_one_fails_immediately(provider, monkeypatch):
    """可有可无的调用（风格识别）：max_retries=1 + transport_retries=1 时，第一次失败就抛出，不退避重试。"""
    calls = _patch_stream(monkeypatch, [
        _Resp([_sse("x")], fail_after=0),
        _Resp([_sse('{"ok":1}', "stop")]),
    ])
    with pytest.raises(Exception):
        asyncio.run(provider.chat_json([{"role": "user", "content": "x"}], max_retries=1, transport_retries=1))
    assert calls["n"] == 1
