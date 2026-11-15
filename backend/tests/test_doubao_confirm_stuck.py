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
    monkeypatch.setattr(g, "_classify_reject", lambda p: None)
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


# ---------------------------------------------------------------- T-270：确认补发失控
REAL_REPLY_1 = "我将为你生成一条 15 秒、16:9 横屏的动画视频"
REAL_REPLY_2 = "本次使用 Seedance 2.0 Fast 生成，预计等待 10 分钟。视频生成好后，我会主动发送给你。"
REAL_REPLY_3 = "今日视频生成免费额度已用完，本次将消耗付费额度，并使用优先生成通道"
OLD_PROMISE = "确认后我再开始生成视频"


class ChatPage(ConfirmPage):
    """按角色记录消息的 mock：msgs=[(role, text)]；确认卡片文字一直留在对话里（confirm_card=True）。"""

    def __init__(self, msgs, **kw):
        super().__init__(bubbles=[t for r, t in msgs if r == "send"], **kw)
        self.msgs = list(msgs)
        self.quota_ctx = []

    def evaluate(self, js, *args):
        if "__chat_messages__" in js:
            return [{"role": r, "text": t} for r, t in self.msgs]
        if "insertText" in js and args:
            self.msgs.append(("send", args[0]))
        if "ctx" in js and args and isinstance(args[0], list) and "额度已用完" in args[0]:
            return list(self.quota_ctx)
        return super().evaluate(js, *args)


def _setup(gen, page, monkeypatch, base=1):
    pid = id(page)
    gen._prompt_base[pid] = base
    clock = {"t": 1000.0}
    monkeypatch.setattr(da.time, "time", lambda: clock["t"])
    return pid, clock


def test_reply_after_confirm_stops_resend_even_if_wording_unknown(gen, monkeypatch):
    """确认后出现任何新的豆包回复（措辞不在 hints 里）都视为已受理，不补发。"""
    page = ChatPage([("send", "提示词"), ("recv", OLD_PROMISE)])
    pid, clock = _setup(gen, page, monkeypatch)
    assert gen._handle_confirm_for(page) is True            # 首次确认
    assert len(page.typed) == 1
    page.msgs.append(("recv", "一段完全不在关键词里的新回复"))
    for dt in (50, 120, 400):
        clock["t"] = 1000.0 + dt
        assert gen._handle_confirm_for(page) is False
    assert len(page.typed) == 1
    assert pid in gen._accepted
    assert gen._confirm_present(page) is False


def test_real_wording_reply_no_resend(gen, monkeypatch):
    page = ChatPage([("send", "提示词"), ("recv", OLD_PROMISE)])
    pid, clock = _setup(gen, page, monkeypatch)
    assert gen._handle_confirm_for(page) is True
    page.msgs += [("recv", REAL_REPLY_1), ("recv", REAL_REPLY_2), ("recv", REAL_REPLY_3)]
    clock["t"] += 200
    assert gen._handle_confirm_for(page) is False
    assert len(page.typed) == 1
    for k in ("我将为你生成", "预计等待", "视频生成好后", "主动发送给你", "优先生成通道", "消耗付费额度"):
        assert k in da.IN_PROGRESS_HINTS
    # 待确认承诺本身不含任何受理关键词
    assert not any(k in OLD_PROMISE for k in da.IN_PROGRESS_HINTS)


def test_no_reply_resends_once_and_total_max_two(gen, monkeypatch):
    page = ChatPage([("send", "提示词"), ("recv", OLD_PROMISE)])
    pid, clock = _setup(gen, page, monkeypatch)
    assert gen._handle_confirm_for(page) is True
    sent = 1
    for dt in range(50, 1000, 50):
        clock["t"] = 1000.0 + dt
        if gen._handle_confirm_for(page):
            sent += 1
    assert sent == 2 == len(page.typed) == da.MAX_CONFIRM_TOTAL
    assert da.MAX_CONFIRM_RESEND == 1
    assert gen._confirm_total[pid] == 2
    # _do_confirm 本身也不会越过总上限
    gen._do_confirm(page, force=True)
    assert len(page.typed) == 2


def test_stuck_branch_never_exceeds_total_then_failed_confirm(gen, monkeypatch, caplog):
    page = ChatPage([("send", "提示词"), ("recv", OLD_PROMISE)])
    pid = id(page)
    gen._prompt_base[pid] = 1
    gen._prompt_sent_at[pid] = 0.0
    clock = {"t": 0.0}
    monkeypatch.setattr(da.time, "time", lambda: clock["t"])
    monkeypatch.setattr(da.time, "sleep", lambda s: clock.__setitem__("t", clock["t"] + s))
    caplog.set_level(logging.INFO)
    assert gen.wait_for_video(page, timeout=1200) is None
    assert len(page.typed) <= da.MAX_CONFIRM_TOTAL
    assert gen.last_fail["code"] == "CONFIRM"
    assert "https://www.doubao.com/chat/999" in gen.last_fail["msg"]
    assert "[DOUBAO_STAGE] FAILED_CONFIRM" in caplog.text


def test_wait_loop_reply_after_confirm_no_stuck_failure(gen, monkeypatch, caplog):
    """确认后豆包已回复（措辞未知）：等待循环不强制补发、不判 FAILED_CONFIRM，而是一直等到超时。"""
    page = ChatPage([("send", "提示词"), ("recv", OLD_PROMISE)])
    pid = id(page)
    gen._prompt_base[pid] = 1
    gen._prompt_sent_at[pid] = 0.0
    clock = {"t": 0.0}
    monkeypatch.setattr(da.time, "time", lambda: clock["t"])
    monkeypatch.setattr(da.time, "sleep", lambda s: clock.__setitem__("t", clock["t"] + s))
    clock["t"] = 100.0
    assert gen._handle_confirm_for(page) is True
    page.msgs.append(("recv", "某种未知措辞的受理回复"))
    caplog.set_level(logging.INFO)
    gen.wait_for_video(page, timeout=600)
    assert len(page.typed) == 1
    assert gen.last_fail["code"] == "TIMEOUT"
    assert "FAILED_CONFIRM" not in caplog.text


def test_paid_quota_sentence_not_blocked_and_logged(gen, caplog):
    """「免费额度已用完…消耗付费额度」不算额度耗尽，只打 PAID_QUOTA；真耗尽仍拦截。"""
    page = ChatPage([("send", "p")])
    caplog.set_level(logging.INFO)
    page.quota_ctx = [REAL_REPLY_3]
    assert da.DoubaoVideoGenerator._quota_blocked(gen, page) is False
    gen._note_paid_quota(page)
    gen._note_paid_quota(page)
    assert caplog.text.count("[DOUBAO_STAGE] PAID_QUOTA") == 1
    page.quota_ctx = ["您当前为免费体验套餐，今日额度已用完，请升级正式订阅"]
    assert da.DoubaoVideoGenerator._quota_blocked(gen, page) is True
