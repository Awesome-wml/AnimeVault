"""替身开关：关闭时走原 HTTP 路径，打开时不发请求；替身 LLM 内容能被真实解析逻辑解析"""
import asyncio

import pytest

from core.prompt_tpl import ASSET_EXTRACT_PROMPT, CHARACTER_EXTRACT_PROMPT, NOVEL_POLISH_PROMPT, SHOT_SPLIT_PROMPT
from core.llm_factory import safe_format
from core.providers import fake
from core.providers.llm_provider import DoubaoLLMProvider

JSON_SYSTEM = {"role": "system", "content": "你必须严格按照要求的JSON格式输出，不要有任何额外的解释、markdown标记或其他文字。"}


class _Resp:
    status_code = 200

    def raise_for_status(self):
        pass

    def json(self):
        return {"choices": [{"message": {"content": "真实接口的回答"}}]}


class _RecordingClient:
    def __init__(self):
        self.calls = []

    async def post(self, url, headers=None, json=None):
        self.calls.append(url)
        return _Resp()


def _call(provider):
    client = _RecordingClient()
    payload = {"model": "glm-4.5-flash", "messages": [{"role": "user", "content": "你好"}]}
    out = asyncio.run(provider._chat_with_retry(client, "https://example.invalid/chat/completions", payload))
    return out, client.calls


def test_switch_off_uses_real_http_path(monkeypatch):
    monkeypatch.delenv("DONGAI_FAKE_PROVIDERS", raising=False)
    assert fake.enabled() is False
    out, calls = _call(DoubaoLLMProvider(api_key="k"))
    assert out == "真实接口的回答" and calls == ["https://example.invalid/chat/completions"]


@pytest.mark.parametrize("value", ["0", "", "false"])
def test_switch_off_values(monkeypatch, value):
    monkeypatch.setenv("DONGAI_FAKE_PROVIDERS", value)
    assert fake.enabled() is False


def test_switch_on_skips_http(monkeypatch):
    monkeypatch.setenv("DONGAI_FAKE_PROVIDERS", "1")
    out, calls = _call(DoubaoLLMProvider(api_key="k"))
    assert calls == [] and out.startswith("暴雨演武场")


def _json_reply(prompt: str) -> dict:
    text = fake.llm_reply([JSON_SYSTEM, {"role": "user", "content": prompt}])
    return DoubaoLLMProvider._parse_json_lenient(text)


def test_fake_llm_follows_template_type():
    assets = _json_reply(safe_format(ASSET_EXTRACT_PROMPT, novel_text="x", style_block=""))
    assert set(assets) == {"characters", "props", "scenes"}
    chars = _json_reply(safe_format(CHARACTER_EXTRACT_PROMPT, novel_text="x", style_block=""))
    assert set(chars) == {"characters"}
    segs = _json_reply(safe_format(SHOT_SPLIT_PROMPT, novel_paragraph="x", style_block="", asset_block="", genre_rhythm=""))
    assert [s["segment_no"] for s in segs["segments"]] == [1, 2, 3]
    assert all(s["lines"] and s["beats"] for s in segs["segments"])
    # 旧版模板（JSON 示例是 "shots"）仍返回一镜一声，用来测兼容
    legacy = _json_reply('JSON 结构如下：{"shots": [...]}')
    assert [s["shot_no"] for s in legacy["shots"]] == [1, 2, 3]
    polished = fake.llm_reply([{"role": "user", "content": safe_format(
        NOVEL_POLISH_PROMPT, novel_text="原文一句。", person_rule="", genre_rhythm="")}])
    assert polished == "（润色稿）原文一句。"


def test_fake_media_fixtures_are_valid():
    assert fake.image_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    assert b"ftyp" in fake.video_bytes()[:64]
    assert len(fake.speech_bytes()) > 1000
