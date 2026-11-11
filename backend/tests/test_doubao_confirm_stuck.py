"""T-269：豆包卡在「确认后我再开始生成视频」的自愈。纯 mock 页面，不连豆包。"""
import logging

import pytest

from core import doubao_automation as da


class ConfirmPage:
    """bubbles: 自己发的气泡；confirm_card: 页面是否有确认提示；typed: 记录打字发出的文本。"""

    def __init__(self, bubbles=None, confirm_card=True, in_progress=False, url="https://www.doubao.com/chat/999"):
        self.bubbles = list(bubbles or [])
        self.confirm_card = confirm_card
        self.in_progress = in_progress
        self.url = url
        self.typed = []
        self.keyboard = self

    def press(self, key):
        pass

    def evaluate(self, js, *args):
        if "send-msg-bubble" in js:
            return list(self.bubbles)
        if "insertText" in js and args:
            self.typed.append(args[0])
            self.bubbles.append(args[0])
            return None
        if "button,[role=button]" in js:
            return False
        if "contenteditable=true]');\n                return ed" in js:
            return ""
        if args and isinstance(args[0], list):
            kws = args[0]
            if any(k in kws for k in da.IN_PROGRESS_HINTS):
                return self.in_progress
            if any(k in kws for k in da.CONFIRM_HINTS):
                return self.confirm_card
        return False


@pytest.fixture
def gen(tmp_path, monkeypatch):
    monkeypatch.setenv("DONGAI_FAKE_PROVIDERS", "1")
    monkeypatch.setattr(da.time, "sleep", lambda s: None)
    g = da.DoubaoVideoGenerator(str(tmp_path))
    monkeypatch.setattr(g, "_quota_blocked", lambda p: False)
    monkeypatch.setattr(g, "_rejected", lambda p: False)
    return g


def test_old_confirm_bubble_not_counted_as_this_round(gen, caplog):
    """旧对话最后气泡是上一轮确认语、新提示词气泡未渲染：仍要发新确认。"""
    page = ConfirmPage(bubbles=["上一轮提示词", da.CONFIRM_REPLY])
    gen._prompt_base[id(page)] = 2  # 发送本轮提示词前有 2 个气泡，新气泡尚未渲染
    caplog.set_level(logging.INFO)
    assert gen._confirm_sent_after_prompt(page) is False
    assert gen._handle_confirm_for(page) is True
    assert page.typed == [da.CONFIRM_REPLY]
    assert "[DOUBAO_STAGE] CONFIRM_SENT" in caplog.text


def test_confirm_after_prompt_bubble_counts(gen):
    page = ConfirmPage(bubbles=["旧", da.CONFIRM_REPLY, "新提示词", da.CONFIRM_REPLY])
    gen._prompt_base[id(page)] = 2
    assert gen._confirm_sent_after_prompt(page) is True
    assert gen._handle_confirm_for(page) is False
    assert page.typed == []


def test_send_prompt_records_base(gen):
    page = ConfirmPage(bubbles=["a", da.CONFIRM_REPLY], in_progress=True)
    gen.send_prompt(page, "新提示词")
    assert gen._prompt_base[id(page)] == 2


def test_wait_loop_resends_confirm_when_card_present(gen, monkeypatch):
    """pid 已在 _confirmed 里，等待循环仍会在冷却后补发。"""
    page = ConfirmPage(bubbles=["p"], confirm_card=True)
    pid = id(page)
    gen._prompt_base[pid] = 0
    gen._confirmed.add(pid)
    gen._confirmed_at[pid] = 1000.0
    clock = {"t": 1000.0}
    monkeypatch.setattr(da.time, "time", lambda: clock["t"])
    # 冷却内不补发
    clock["t"] = 1010.0
    assert gen._handle_confirm_for(page) is False
    clock["t"] = 1000.0 + da.RESEND_COOLDOWN + 1
    assert gen._handle_confirm_for(page) is True
    assert page.typed == [da.CONFIRM_REPLY]


def test_stuck_150s_resend_then_failed_confirm(gen, monkeypatch, caplog):
    page = ConfirmPage(bubbles=["p"], confirm_card=True)
    pid = id(page)
    gen._prompt_base[pid] = 0
    gen._prompt_sent_at[pid] = 0.0
    clock = {"t": 0.0}
    monkeypatch.setattr(da.time, "time", lambda: clock["t"])
    monkeypatch.setattr(da.time, "sleep", lambda s: clock.__setitem__("t", clock["t"] + s))
    monkeypatch.setattr(gen, "_handle_confirm_for", lambda p: False)  # 只测兜底分支
    caplog.set_level(logging.INFO)
    res = gen.wait_for_video(page, timeout=1200)
    assert res is None
    assert "[DOUBAO_STAGE] CONFIRM_RESEND" in caplog.text
    assert gen.last_fail["code"] == "CONFIRM"
    assert "https://www.doubao.com/chat/999" in gen.last_fail["msg"]
    assert "[DOUBAO_STAGE] FAILED_CONFIRM" in caplog.text
    # 150s 补发 + 60s 宽限，远早于 1200s
    assert clock["t"] < 300
