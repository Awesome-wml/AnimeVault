"""wait_for_video 抓直链加固：聚焦聊天区再滚、点回到底部、首轮失败刷新重试、失败原因带对话 URL。

纯单元测试：mock 页面对象，不连豆包、不消耗额度。
"""
import pytest

from core import doubao_automation as da


class FakePage:
    """按调用记录事件；evaluate 按 JS 片段关键字返回预设值。"""

    def __init__(self, url="https://www.doubao.com/chat/12345", covers_after_goto=False,
                 covers=True, ready=True, hooks=None):
        self.url = url
        self.events = []
        self.ready = ready
        self.covers = covers
        self.covers_after_goto = covers_after_goto
        self.reloaded = False
        self.video_src = None

        self.mouse = self
        self.keyboard = self
        self.hooks = hooks or {}

    # mouse / keyboard
    def move(self, x, y):
        self.events.append(("move", x, y))

    def wheel(self, dx, dy):
        self.events.append(("wheel", dy))

    def click(self, x, y):
        self.events.append(("click", x, y))
        if "click" in self.hooks:
            self.hooks["click"](self)

    def press(self, key):
        self.events.append(("press", key))

    def goto(self, url):
        self.events.append(("goto", url))
        self.reloaded = True

    def screenshot(self, path):
        self.events.append(("shot", path))

    def evaluate(self, js, *args):
        if "视频生成好了" in js:
            return self.ready
        if "video[src^" in js:  # _result_ready：结果封面/播放器已挂载
            return self.ready
        if "kws.some" in js and args and "视频生成好了" in args[0]:  # _page_contains 完成文本
            return self.ready
        if "bestD" in js:  # _scroll_cover_into_view：无需调整
            return None
        if "overflowY" in js and "best" in js:
            return {"x": 700, "y": 350}
        if "回到底部" in js:
            self.events.append(("back_to_bottom",))
            return True
        if "scrollTop" in js:
            return None
        if "querySelectorAll('img')" in js and "scrollIntoView" in js:
            if self.covers or (self.covers_after_goto and self.reloaded):
                return [{"cx": 640, "cy": 500, "area": 1}]
            return []
        if "currentSrc" in js:
            return self.video_src
        if "img').length" in js:
            return True
        return False


@pytest.fixture
def gen(tmp_path, monkeypatch):
    monkeypatch.setenv("DONGAI_FAKE_PROVIDERS", "1")
    monkeypatch.setattr(da.time, "sleep", lambda s: None)
    g = da.DoubaoVideoGenerator(str(tmp_path))
    monkeypatch.setattr(g, "_quota_blocked", lambda p: False)
    monkeypatch.setattr(g, "_classify_reject", lambda p: None)
    monkeypatch.setattr(g, "_handle_confirm_for", lambda p: False)
    monkeypatch.setattr(g, "_in_progress", lambda p: True)
    monkeypatch.setattr(g, "_wait_js", lambda *a, **k: True)
    return g


def test_focus_chat_before_scroll(gen):
    page = FakePage()
    gen._scroll_chat_to_bottom(page)
    kinds = [e[0] for e in page.events]
    assert kinds.index("move") < kinds.index("wheel")
    assert ("move", 700, 350) in page.events
    assert "back_to_bottom" in kinds


def test_got_url_by_clicking_cover(gen):
    def on_click(p):
        p.video_src = "https://v26-vdl.doubao.com/a/b.mp4"
    page = FakePage(hooks={"click": on_click})
    url = gen.wait_for_video(page, timeout=30)
    assert url == "https://v26-vdl.doubao.com/a/b.mp4"
    assert not page.reloaded
    assert gen.last_fail is None


def test_response_listener_url_wins_without_cover(gen):
    page = FakePage(covers=False)
    gen.video_urls.append("https://v11-vdl.doubao.com/x.mp4")
    assert gen.wait_for_video(page, timeout=30) == "https://v11-vdl.doubao.com/x.mp4"
    assert not any(e[0] == "click" for e in page.events)


def test_refresh_and_retry_after_first_round_fails(gen):
    def on_click(p):
        p.video_src = "https://v26-vdl.doubao.com/after-refresh.mp4"
    # 刷新前没有封面，刷新后才有
    page = FakePage(covers=False, covers_after_goto=True, hooks={"click": on_click})
    url = gen.wait_for_video(page, timeout=30)
    assert ("goto", "https://www.doubao.com/chat/12345") in page.events
    assert url == "https://v26-vdl.doubao.com/after-refresh.mp4"


def test_no_url_error_carries_conversation_url(gen, tmp_path):
    page = FakePage(covers=False)
    assert gen.wait_for_video(page, timeout=30) is None
    assert ("goto", "https://www.doubao.com/chat/12345") in page.events  # 失败前刷新重试过
    assert gen.last_fail["code"] == "NO_URL"
    assert "https://www.doubao.com/chat/12345" in gen.last_fail["msg"]
    assert "没抓到直链" in gen.last_fail["msg"] and "手动下载" in gen.last_fail["msg"]
    assert gen.last_fail["conversation_url"] == "https://www.doubao.com/chat/12345"


def test_rejected_and_quota_and_timeout_are_distinguished(gen, monkeypatch):
    # 风控拦截 → REJECTED，保留命中片段
    monkeypatch.setattr(gen, "_classify_reject",
                        lambda p: {"kind": "risk", "kw": "版权限制", "text": "生成的视频可能涉及版权限制"})
    assert gen.wait_for_video(FakePage(), timeout=30) is None
    assert gen.last_fail["code"] == "REJECTED"
    assert gen.last_fail["detail"] == "生成的视频可能涉及版权限制"
    # 服务端生成失败（非风控）→ GEN_FAILED，可重试
    monkeypatch.setattr(gen, "_classify_reject",
                        lambda p: {"kind": "gen_fail", "kw": "生成失败", "text": "视频生成失败，生成额度未扣除"})
    assert gen.wait_for_video(FakePage(), timeout=30) is None
    assert gen.last_fail["code"] == "GEN_FAILED"
    monkeypatch.setattr(gen, "_classify_reject", lambda p: None)
    monkeypatch.setattr(gen, "_quota_blocked", lambda p: True)
    assert gen.wait_for_video(FakePage(), timeout=30) is None
    assert gen.last_fail["code"] == "QUOTA"
    monkeypatch.setattr(gen, "_quota_blocked", lambda p: False)
    assert gen.wait_for_video(FakePage(ready=False), timeout=0) is None
    assert gen.last_fail["code"] == "TIMEOUT"


def test_stage_tags_logged(gen, caplog):
    import logging
    caplog.set_level(logging.INFO)
    gen.wait_for_video(FakePage(covers=False), timeout=30)
    text = caplog.text
    for tag in ("WAITING_CONFIRM", "GENERATING", "READY_PENDING_URL", "FETCH_SCROLL",
                "FETCH_COVER", "RETRY_REFRESH", "FAILED_NO_URL"):
        assert f"[DOUBAO_STAGE] {tag}" in text
