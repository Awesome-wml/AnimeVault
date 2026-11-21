"""风格 AI 识别：模型结果必须落在风格库里，失败退回关键词规则；只给待识别的作品自动写回。"""
import asyncio

from core import style_suggest as S
from core.prompt_registry import build_messages

XIANXIA = "暴雨如注。沈砚感觉到修仙者的威压，体内灵力开始运转，他不是修炼大宗门的弟子，阵法青光升起。" * 5
FAMILY = "婆婆把彩礼的事又提了一遍，小姑子在旁边帮腔，儿媳低着头不说话，饭桌上谁也不让谁。" * 5


class _LLM:
    def __init__(self, reply=None, exc=None):
        self.reply, self.exc, self.calls = reply, exc, []

    async def chat_json(self, messages, **kw):
        self.calls.append((messages, kw))
        if self.exc:
            raise self.exc
        return self.reply


def test_prompt_lists_library_ids_and_excerpt():
    m = build_messages("style_suggest", novel_excerpt="片段X", medium_options=S.medium_options(), genre_options=S.genre_options())
    text = "\n".join(x["content"] for x in m)
    assert "片段X" in text and "cg3d｜3D 国漫" in text and "xianxia｜仙侠" in text and '"medium"' in text


def test_model_result_is_validated():
    got = asyncio.run(S.suggest_style(_LLM({"medium": "cg3d", "genre": "xianxia", "confidence": 0.9, "reason": "修仙世界观"}), XIANXIA))
    assert got["medium"] == "cg3d" and got["genre"] == "仙侠" and got["source"] == "ai" and got["confidence"] == 0.9
    # 模型填了名称而不是 id：按名称也认
    got = asyncio.run(S.suggest_style(_LLM({"medium": "cg3d", "genre": "仙侠"}), XIANXIA))
    assert got["genre_id"] == "xianxia"


def test_invalid_or_failed_model_falls_back_to_rules():
    bad = asyncio.run(S.suggest_style(_LLM({"medium": "水彩", "genre": "武侠"}), XIANXIA))
    assert bad["source"] == "rule" and bad["genre_id"] == "xianxia" and bad["medium"] == "cg3d"
    err = asyncio.run(S.suggest_style(_LLM(exc=RuntimeError("no key")), FAMILY))
    assert err["source"] == "rule" and err["genre_id"] == "jiating" and err["medium"] == "realistic"
    none = asyncio.run(S.suggest_style(None, "今天天气不错。" * 40))
    assert none["source"] == "rule" and none["confidence"] < 0.5


def test_excerpt_keeps_head_and_tail():
    text = "头" * 3000 + "尾" * 3000
    ex = S.novel_excerpt(text)
    assert ex.startswith("头") and ex.endswith("尾") and len(ex) < 3400


class _Col:
    def __init__(self):
        self.updates = []

    async def update_one(self, flt, upd):
        self.updates.append(upd["$set"])


class _DB:
    def __init__(self):
        self.projects = _Col()


def test_auto_only_for_pending_projects_with_enough_text():
    db = _DB()
    user_chosen = {"_id": 1, "style_source": "user", "medium": "realistic"}
    assert asyncio.run(S.auto_style_if_needed(db, user_chosen, None, XIANXIA)) is None
    legacy = {"_id": 2, "medium": "realistic"}                    # 老作品没有 style_source：不动
    assert asyncio.run(S.auto_style_if_needed(db, legacy, None, XIANXIA)) is None
    pending = {"_id": 3, "style_source": "auto", "medium": "realistic"}
    assert asyncio.run(S.auto_style_if_needed(db, pending, None, "太短")) is None
    s = asyncio.run(S.auto_style_if_needed(db, pending, None, XIANXIA))
    assert s and pending["medium"] == "cg3d" and pending["genre"] == "仙侠" and pending["style_source"] == "ai"
    assert db.projects.updates[-1]["style_reason"].startswith("3D 国漫 · 仙侠")
    assert not S.needs_auto(pending)   # 识别过一次就不再自动识别


def test_model_is_tried_once_without_backoff():
    """风格识别可有可无：只问一次、限流不退避重试，超时也直接退回规则。"""
    llm = _LLM(exc=RuntimeError("429 rate limited"))
    got = asyncio.run(S.suggest_style(llm, XIANXIA))
    assert got["source"] == "rule" and len(llm.calls) == 1
    assert llm.calls[0][1]["max_retries"] == 1 and llm.calls[0][1]["transport_retries"] == 1

    class Slow(_LLM):
        async def chat_json(self, messages, **kw):
            await asyncio.sleep(5)

    old, S.AI_TIMEOUT_SECONDS = S.AI_TIMEOUT_SECONDS, 0.05
    try:
        assert asyncio.run(S.suggest_style(Slow(), XIANXIA))["source"] == "rule"
    finally:
        S.AI_TIMEOUT_SECONDS = old
