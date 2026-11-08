"""视频账号「检查登录」三条路径：复用已开 Chrome 的调试端口、资料目录被占用立即报错、启动检查超时报错。

用本机 Chrome + 临时资料目录 + 本地 http 页面，不访问真实豆包，不碰 .doubao_profiles。
"""
import asyncio
import json
import os
import signal
import socket
import subprocess
import tempfile
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from core import doubao_chrome
from core.doubao_account_pool import DoubaoAccountPool
from core.doubao_chrome import (LoginCheckTimeout, ProfileInUse, check_account_login, launch_chrome,
                                probe_debug_port)

pytestmark = pytest.mark.skipif(not Path(doubao_chrome.CHROME_PATH).exists(), reason="本机没有 Google Chrome")

LOGGED_IN_PAGE = "<html><body><div contenteditable=true>豆包对话</div></body></html>"
LOGGED_OUT_PAGE = "<html><body><button>登录</button></body></html>"


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path.startswith("/hang"):
            time.sleep(120)  # 永不及时响应，模拟页面卡住
            return
        body = (LOGGED_OUT_PAGE if self.path.startswith("/logout") else LOGGED_IN_PAGE).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Set-Cookie", "sessionid=e2e-session; Path=/; Max-Age=3600")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture(scope="module")
def site():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class FakePool:
    """只记录写入，不连数据库"""

    def __init__(self, account):
        self.account = account
        self.calls = []

    @property
    def accounts(self):
        return [self.account]

    def update_account(self, account_id, patch):
        self.account.update(patch)
        self.calls.append(("update", patch))

    def set_cookies(self, account_id, cookies):
        self.calls.append(("set_cookies", cookies))

    def set_login_state(self, account_id, logged_in):
        self.calls.append(("set_login_state", logged_in))

    def record_check(self, account_id, ok, error=None):
        self.calls.append(("record_check", ok, error))

    def set_quota(self, account_id, quota):
        self.calls.append(("set_quota", quota))


def _page_targets(port):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(f"http://127.0.0.1:{port}/json/list", timeout=3) as r:
        return [t for t in json.loads(r.read()) if t.get("type") == "page"]


def _procs_using(path: str) -> str:
    return subprocess.run(["pgrep", "-f", path], capture_output=True, text=True).stdout.strip()


@pytest.fixture
def tmp_root():
    with tempfile.TemporaryDirectory(prefix="dongai-login-") as d:
        yield Path(d)


@pytest.fixture
def user_chrome(tmp_root, site):
    """模拟用户点「打开」后开着的 Chrome：统一启动函数 + 调试端口（测试里加 headless）"""
    port = _free_port()
    profile = tmp_root / "profile_open"
    proc = launch_chrome(str(profile), port, site + "/", extra_args=["--headless=new"])
    for _ in range(100):
        if probe_debug_port(port):
            break
        time.sleep(0.1)
    else:
        proc.kill()
        pytest.fail("Chrome 调试端口没有起来")
    yield {"port": port, "profile_dir": "profile_open", "proc": proc}
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    proc.wait(timeout=10)


def test_cdp_reuse_saves_cookies_and_keeps_user_browser(user_chrome, tmp_root, site):
    account = {"id": "account_7", "profile_dir": user_chrome["profile_dir"], "cookies": [],
               "debug_port": user_chrome["port"]}
    pool = FakePool(account)
    tabs_before = len(_page_targets(user_chrome["port"]))

    result = asyncio.run(check_account_login(pool, account, tmp_root, url=site + "/", settle_ms=300, timeout=30))

    assert result["via"] == "cdp" and result["logged_in"] is True
    saved = [c for c in pool.calls if c[0] == "set_cookies"]
    assert saved and any(ck["name"] == "sessionid" and ck["value"] == "e2e-session" for ck in saved[0][1])
    assert ("record_check", True, None) in pool.calls
    # 已登录时顺带读一次额度（本地页面不请求额度接口 → ok=False；替身模式下是固定数据），都写回账号
    assert [c for c in pool.calls if c[0] == "set_quota"]
    # 用户的浏览器还在，自己开的检查标签页已关掉
    assert user_chrome["proc"].poll() is None
    assert probe_debug_port(user_chrome["port"])
    assert len(_page_targets(user_chrome["port"])) == tabs_before


def test_cdp_logged_out_does_not_open_another_window(user_chrome, tmp_root, site, monkeypatch):
    account = {"id": "account_8", "profile_dir": user_chrome["profile_dir"], "cookies": [],
               "debug_port": user_chrome["port"]}
    pool = FakePool(account)
    monkeypatch.setattr(doubao_chrome, "launch_chrome", lambda *a, **k: pytest.fail("不应再开窗口"))

    result = asyncio.run(check_account_login(pool, account, tmp_root, url=site + "/logout", settle_ms=300, timeout=30))

    assert result["via"] == "cdp" and result["logged_in"] is False
    assert "已打开的 Chrome" in result["message"]
    assert ("set_login_state", False) in pool.calls
    assert user_chrome["proc"].poll() is None


def test_locked_profile_fails_immediately(tmp_root, site, monkeypatch):
    profile = tmp_root / "profile_locked"
    profile.mkdir()
    # 和 Chrome 一样：SingletonLock 是指向「主机名-pid」的符号链接，pid 用本进程（存活）
    os.symlink(f"{socket.gethostname()}-{os.getpid()}", profile / "SingletonLock")
    account = {"id": "account_9", "profile_dir": "profile_locked", "cookies": [], "debug_port": _free_port()}
    pool = FakePool(account)

    async def _no_browser(*a, **k):
        pytest.fail("目录被占用时不应启动浏览器")
    monkeypatch.setattr(doubao_chrome, "run_login_check", _no_browser)

    t0 = time.monotonic()
    with pytest.raises(ProfileInUse) as exc:
        asyncio.run(check_account_login(pool, account, tmp_root, url=site + "/"))
    assert time.monotonic() - t0 < 3
    assert "关闭" in str(exc.value)
    assert pool.calls[-1][0] == "record_check" and pool.calls[-1][1] is False


def test_stale_lock_is_ignored(tmp_root):
    profile = tmp_root / "profile_stale"
    profile.mkdir()
    os.symlink(f"{socket.gethostname()}-999999", profile / "SingletonLock")
    assert doubao_chrome.profile_lock_pid(str(profile)) is None


def test_launch_timeout_reports_error_and_cleans_up(tmp_root, site):
    account = {"id": "account_10", "profile_dir": "profile_timeout", "cookies": [], "debug_port": _free_port()}
    pool = FakePool(account)
    profile_path = str(tmp_root / "profile_timeout")

    t0 = time.monotonic()
    with pytest.raises(LoginCheckTimeout) as exc:
        asyncio.run(check_account_login(pool, account, tmp_root, url=site + "/hang", settle_ms=300,
                                        timeout=6, headless=True))
    assert time.monotonic() - t0 < 20
    assert "超时" in str(exc.value)
    assert pool.calls[-1][0] == "record_check" and pool.calls[-1][1] is False
    # Playwright 及其启动的 Chrome 都已清理
    for _ in range(50):
        if not _procs_using(profile_path):
            break
        time.sleep(0.2)
    assert not _procs_using(profile_path), "超时后仍有进程占用临时资料目录"


def test_port_allocation_is_unique():
    used = [19301, 19302]
    assert doubao_chrome.allocate_port("account_3", used) == 19303
    p = doubao_chrome.allocate_port("account_1", used + [19303])
    assert p not in used + [19303] and doubao_chrome.DEBUG_PORT_BASE < p < doubao_chrome.DEBUG_PORT_BASE + 600
    assert doubao_chrome.allocate_port("custom", used) not in used


def test_login_status_requires_cookies_and_successful_check():
    st = DoubaoAccountPool.login_status
    assert st({"logged_in": True, "cookies": [{"name": "sessionid"}]}) == "logged_in"
    assert st({"logged_in": True, "cookies": []}) == "need_recheck"
    assert st({"logged_in": True, "cookies": [{"name": "s"}], "last_check": {"ok": False}}) == "need_recheck"
    assert st({"logged_in": False, "cookies": []}) == "logged_out"
    assert st({"logged_in": False, "cookies": [], "last_check": {"ok": True}}) == "logged_out"
