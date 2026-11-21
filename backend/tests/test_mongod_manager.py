"""MongodManager 测试：单元部分用假 mongod（tests/fake_mongod.py），不依赖真 mongod；
集成部分在设置了 DONGAI_MONGOD_BIN（真 mongod 路径）时才运行。"""
import os
import socket
import sys
import time
from pathlib import Path

import pytest

from desktop.mongod_manager import MongodError, MongodManager

FAKE = Path(__file__).with_name("fake_mongod.py")
posix_only = pytest.mark.skipif(sys.platform == "win32", reason="信号语义仅 POSIX")


def make(tmp_path, mode="ok", delay=0, monkeypatch=None, **kw):
    if monkeypatch:
        monkeypatch.setenv("FAKE_MONGOD_MODE", mode)
        monkeypatch.setenv("FAKE_MONGOD_DELAY", str(delay))
    kw.setdefault("ping", False)
    kw.setdefault("ready_timeout", 5)
    return MongodManager([sys.executable, str(FAKE)], tmp_path / "data", **kw)


def can_connect(port):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except OSError:
        return False


def test_start_stop(tmp_path, monkeypatch):
    m = make(tmp_path, monkeypatch=monkeypatch)
    url = m.start()
    try:
        assert url == f"mongodb://127.0.0.1:{m.port}/"
        assert m.is_running and m.pid
        assert can_connect(m.port)
        assert m.start() == url  # 重复 start 幂等
    finally:
        m.stop()
    assert not m.is_running
    assert not can_connect(m.port)
    assert (tmp_path / "data").is_dir()


def test_context_manager_and_random_port(tmp_path, monkeypatch):
    with make(tmp_path, monkeypatch=monkeypatch) as m:
        assert m.port and m.port != 27017
        assert m.is_running
    assert not m.is_running


def test_ready_timeout(tmp_path, monkeypatch):
    m = make(tmp_path, "slow", 3, monkeypatch, ready_timeout=0.5)
    with pytest.raises(MongodError, match="未就绪"):
        m.start()
    assert not m.is_running  # 超时后进程已被清理


def test_exit_during_startup(tmp_path, monkeypatch):
    m = make(tmp_path, "exit", monkeypatch=monkeypatch)
    with pytest.raises(MongodError, match="返回码 3"):
        m.start()


def test_missing_binary(tmp_path):
    m = MongodManager(tmp_path / "nope", tmp_path / "data", ping=False)
    with pytest.raises(MongodError, match="无法启动"):
        m.start()


@posix_only
def test_stop_force_kills_when_term_ignored(tmp_path, monkeypatch):
    m = make(tmp_path, "ignore_term", monkeypatch=monkeypatch, stop_timeout=0.5)
    m.start()
    t = time.time()
    m.stop()
    assert not m.is_running
    assert time.time() - t < 5


def test_stop_without_start_is_noop(tmp_path):
    MongodManager("x", tmp_path / "d").stop()


def test_ensure_running_restarts_after_crash(tmp_path, monkeypatch):
    m = make(tmp_path, monkeypatch=monkeypatch)
    url = m.start()
    try:
        m._proc.kill()
        m._proc.wait()
        assert not m.is_running
        assert m.ensure_running() == url  # 沿用原端口
        assert m.is_running and m.restart_count == 1
        assert m.ensure_running() == url and m.restart_count == 1  # 在跑就不重启
    finally:
        m.stop()


def test_ensure_running_gives_up_after_max_restarts(tmp_path, monkeypatch):
    m = make(tmp_path, "crash_after", 0.5, monkeypatch, max_restarts=2)
    m.start()
    try:
        for _ in range(2):
            m._proc.wait(timeout=5)
            m.ensure_running()
        m._proc.wait(timeout=5)
        with pytest.raises(MongodError, match="放弃重启"):
            m.ensure_running()
    finally:
        m.stop()


def test_ensure_running_starts_if_never_started(tmp_path, monkeypatch):
    m = make(tmp_path, monkeypatch=monkeypatch)
    try:
        m.ensure_running()
        assert m.is_running
    finally:
        m.stop()


def test_fixed_port_in_use_raises(tmp_path, monkeypatch):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen(1)
        m = make(tmp_path, monkeypatch=monkeypatch, port=s.getsockname()[1])
        with pytest.raises(MongodError, match="已被占用"):
            m.start()


def test_stale_lock_is_flagged_not_deleted(tmp_path, monkeypatch):
    d = tmp_path / "data"
    d.mkdir()
    (d / "mongod.lock").write_text("999999999")  # 不存在的 pid
    m = make(tmp_path, monkeypatch=monkeypatch)
    try:
        m.start()
        assert m.recovered_unclean is True
        assert (d / "mongod.lock").read_text() == "999999999"  # 交给 mongod 自己处理
    finally:
        m.stop()


def test_lock_held_by_live_process_refuses(tmp_path, monkeypatch):
    d = tmp_path / "data"
    d.mkdir()
    (d / "mongod.lock").write_text(str(os.getpid()))  # 当前测试进程，肯定活着
    m = make(tmp_path, monkeypatch=monkeypatch)
    with pytest.raises(MongodError, match="占用"):
        m.start()


def test_empty_lock_is_clean(tmp_path, monkeypatch):
    d = tmp_path / "data"
    d.mkdir()
    (d / "mongod.lock").write_text("")
    m = make(tmp_path, monkeypatch=monkeypatch)
    try:
        m.start()
        assert m.recovered_unclean is False
    finally:
        m.stop()


# ---------------- 真 mongod 集成测试 ----------------
REAL = os.environ.get("DONGAI_MONGOD_BIN")
real_only = pytest.mark.skipif(not REAL, reason="未设置 DONGAI_MONGOD_BIN")


@real_only
def test_real_mongod_lifecycle_and_kill9_recovery(tmp_path):
    from pymongo import MongoClient, WriteConcern
    m = MongodManager(REAL, tmp_path / "data")
    url = m.start()
    try:
        c = MongoClient(url, serverSelectionTimeoutMS=3000)
        c["dongai_spike_test"]["a"].insert_many([{"i": i} for i in range(100)])
        c["dongai_spike_test"].get_collection("b", write_concern=WriteConcern(j=True)).insert_one({"k": 1})
        c.close()
        m._proc.kill()  # 模拟崩溃（kill -9）
        m._proc.wait()
        assert not m.is_running
        assert m.ensure_running() == url
        assert m.restart_count == 1
        c = MongoClient(url, serverSelectionTimeoutMS=3000)
        assert c["dongai_spike_test"]["b"].count_documents({}) == 1  # j=True 的写入崩溃后仍在
        c.close()
    finally:
        m.stop()
    assert not m.is_running
    # 干净停止后再起，数据仍在
    m2 = MongodManager(REAL, tmp_path / "data")
    try:
        c = MongoClient(m2.start(), serverSelectionTimeoutMS=3000)
        assert c["dongai_spike_test"]["b"].count_documents({}) == 1
        c.close()
    finally:
        m2.stop()


# ---------- 认证（DONGAI_MONGOD_AUTH=1，默认关） ----------
class _FakeAdmin:
    def __init__(self, server, url):
        self.server, self.url = server, url

    def command(self, name, *args, **kwargs):
        from pymongo.errors import OperationFailure
        authed = "@" in self.url
        if name == "ping":
            return {"ok": 1}
        if name == "createUser":
            if self.server["users"]:
                raise OperationFailure("command createUser requires authentication")      # 已有用户：本机免认证例外失效
            self.server["users"][args[0]] = kwargs["pwd"]
            return {"ok": 1}
        if name == "listDatabases":
            user, pwd = self.url.split("//")[1].split("@")[0].split(":") if authed else ("", "")
            if self.server["users"].get(user) != pwd:
                raise OperationFailure("Authentication failed.")
            return {"ok": 1}
        raise AssertionError(name)


def _fake_client(server):
    class Client:
        def __init__(self, url, **kw):
            self.admin = _FakeAdmin(server, url)

        def close(self):
            pass
    return Client


def _auth_mgr(tmp_path, monkeypatch, server):
    import pymongo
    from desktop.mongod_manager import MongodManager
    monkeypatch.setattr(pymongo, "MongoClient", _fake_client(server))
    m = MongodManager("/bin/true", tmp_path / "data", auth=True, credentials_path=tmp_path / "mongod.auth", ping=False)
    m.port = 27999
    return m


def test_auth_flag_adds_argument_and_plain_mode_is_unchanged(tmp_path):
    from desktop.mongod_manager import MongodManager
    plain = MongodManager("/bin/true", tmp_path / "d", port=27998, ping=False)
    assert "--auth" not in plain._build_cmd() and plain.url == "mongodb://127.0.0.1:27998/"
    secure = MongodManager("/bin/true", tmp_path / "d", port=27998, ping=False, auth=True)
    assert "--auth" in secure._build_cmd()
    assert secure.url == "mongodb://127.0.0.1:27998/"            # 账号建好之前还是不带凭据的地址


def test_first_start_creates_user_and_saves_credentials_privately(tmp_path, monkeypatch):
    import json
    import stat
    server = {"users": {}}
    m = _auth_mgr(tmp_path, monkeypatch, server)
    m._ensure_user()
    creds = json.loads((tmp_path / "mongod.auth").read_text())
    assert creds["user"] == "dongai" and len(creds["password"]) >= 24 and server["users"] == {"dongai": creds["password"]}
    assert m.url.startswith("mongodb://dongai:") and m.url.endswith("@127.0.0.1:27999/?authSource=admin")
    if sys.platform != "win32":
        assert stat.S_IMODE((tmp_path / "mongod.auth").stat().st_mode) == 0o600
    # 第二次启动：用存下的凭据，不再建用户、密码不变
    again = _auth_mgr(tmp_path, monkeypatch, server)
    again._ensure_user()
    assert again.url == m.url and len(server["users"]) == 1


def test_lost_credentials_with_existing_users_fails_with_recovery_hint(tmp_path, monkeypatch):
    from desktop.mongod_manager import MongodError
    server = {"users": {"dongai": "原来的密码"}}
    m = _auth_mgr(tmp_path, monkeypatch, server)                  # 凭据文件不在
    with pytest.raises(MongodError) as e:
        m._ensure_user()
    assert "DONGAI_MONGOD_AUTH" in str(e.value) and "数据都在" in str(e.value)
    assert not (tmp_path / "mongod.auth").exists()                # 没建成就不留一个错的凭据文件
