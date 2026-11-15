"""desktop_entry 里 mongod 相关逻辑的单测：路径解析、遗留进程清理、启动/退出清理（用假 mongod）。"""
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

import desktop_entry as de

FAKE = Path(__file__).with_name("fake_mongod.py")
posix_only = pytest.mark.skipif(sys.platform == "win32", reason="信号语义仅 POSIX")


def _spawn_fake(port, tmp_path):
    """拉起假 mongod（命令行里含 fake_mongod，满足 is_mongod_process）；后台线程负责回收，避免僵尸。"""
    p = subprocess.Popen([sys.executable, str(FAKE), "--port", str(port)],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    threading.Thread(target=p.wait, daemon=True).start()
    return p


def _wait_dead(pid, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not de._pid_alive(pid):
            return True
        time.sleep(0.05)
    return False


def test_resolve_bin_env_overrides(monkeypatch, tmp_path):
    monkeypatch.setenv(de.MONGOD_BIN_ENV, str(tmp_path / "x" / "mongod"))
    assert de.resolve_mongod_bin() == tmp_path / "x" / "mongod"


def test_resolve_bin_default_next_to_app(monkeypatch, tmp_path):
    monkeypatch.delenv(de.MONGOD_BIN_ENV, raising=False)
    monkeypatch.setattr(de, "app_dir", lambda: tmp_path)
    name = "mongod.exe" if sys.platform == "win32" else "mongod"
    assert de.resolve_mongod_bin() == tmp_path / "bin" / name


def test_paths_layout(tmp_path):
    assert de.mongo_data_dir(tmp_path) == tmp_path / "mongo"
    assert de.pid_file_path(tmp_path) == tmp_path / "mongod.pid"


def test_cleanup_without_leftovers(tmp_path):
    assert de.cleanup_stale_mongod(tmp_path) == []


def test_cleanup_ignores_dead_pid_and_removes_file(tmp_path):
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    de.pid_file_path(tmp_path).write_text(f"{p.pid}\n")
    assert de.cleanup_stale_mongod(tmp_path) == []
    assert not de.pid_file_path(tmp_path).exists()


@posix_only
def test_cleanup_does_not_kill_non_mongod(tmp_path):
    """pid 被复用给别的程序时不能误杀。"""
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    threading.Thread(target=p.wait, daemon=True).start()
    try:
        de.pid_file_path(tmp_path).write_text(f"{p.pid}\n")
        assert de.cleanup_stale_mongod(tmp_path) == []
        assert de._pid_alive(p.pid)
        assert not de.pid_file_path(tmp_path).exists()
    finally:
        p.kill()


@posix_only
def test_cleanup_kills_leftover_mongod_by_pid_file(tmp_path):
    p = _spawn_fake(de.pick_free_port(), tmp_path)
    time.sleep(0.5)
    de.pid_file_path(tmp_path).write_text(f"{p.pid}\n")
    assert de.cleanup_stale_mongod(tmp_path) == [p.pid]
    assert _wait_dead(p.pid)
    assert not de.pid_file_path(tmp_path).exists()


@posix_only
def test_cleanup_uses_mongod_lock_when_pid_file_missing(tmp_path):
    p = _spawn_fake(de.pick_free_port(), tmp_path)
    time.sleep(0.5)
    (tmp_path / "mongo").mkdir()
    (tmp_path / "mongo" / "mongod.lock").write_text(f"{p.pid}\n")
    assert de.cleanup_stale_mongod(tmp_path) == [p.pid]
    assert _wait_dead(p.pid)


@posix_only
def test_cleanup_force_kills_when_term_ignored(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_MONGOD_MODE", "ignore_term")
    p = _spawn_fake(de.pick_free_port(), tmp_path)
    time.sleep(0.5)
    de.pid_file_path(tmp_path).write_text(f"{p.pid}\n")
    assert de.cleanup_stale_mongod(tmp_path, stop_timeout=0.5) == [p.pid]
    assert _wait_dead(p.pid)


def test_start_missing_binary(monkeypatch, tmp_path):
    from desktop.mongod_manager import MongodError
    monkeypatch.setenv(de.MONGOD_BIN_ENV, str(tmp_path / "nope"))
    with pytest.raises(MongodError):
        de.start_local_mongod(tmp_path)


@posix_only
def test_start_writes_pid_and_stop_cleans(monkeypatch, tmp_path):
    """用假 mongod 走完整的 start_local_mongod / stop_local_mongod（不 ping）。"""
    from desktop import mongod_manager as mm
    wrapper = tmp_path / "fake-mongod-wrapper"
    wrapper.write_text(f"#!/bin/sh\nexec {sys.executable} {FAKE} \"$@\"\n")
    wrapper.chmod(0o755)
    monkeypatch.setenv(de.MONGOD_BIN_ENV, str(wrapper))
    orig = mm.MongodManager.__init__

    def init(self, *a, **kw):
        kw["ping"] = False
        kw["ready_timeout"] = 10
        orig(self, *a, **kw)

    monkeypatch.setattr(mm.MongodManager, "__init__", init)
    data = tmp_path / "data"
    mgr = de.start_local_mongod(data)
    pid = mgr.pid
    try:
        assert mgr.url.startswith("mongodb://127.0.0.1:")
        assert de.pid_file_path(data).read_text().strip() == str(pid)
        assert (data / "mongo").is_dir()
        assert de.is_mongod_process(pid)
    finally:
        de.stop_local_mongod(mgr, data)
    assert _wait_dead(pid)
    assert not de.pid_file_path(data).exists()


@posix_only
def test_second_start_cleans_orphan_after_parent_killed(monkeypatch, tmp_path):
    """模拟后端被 kill -9：mongod 还在、pid 文件还在；下次启动先清掉它。"""
    orphan = _spawn_fake(de.pick_free_port(), tmp_path)
    time.sleep(0.5)
    data = tmp_path / "data"
    data.mkdir()
    de.pid_file_path(data).write_text(f"{orphan.pid}\n")
    wrapper = tmp_path / "w"
    wrapper.write_text(f"#!/bin/sh\nexec {sys.executable} {FAKE} \"$@\"\n")
    wrapper.chmod(0o755)
    monkeypatch.setenv(de.MONGOD_BIN_ENV, str(wrapper))
    from desktop import mongod_manager as mm
    orig = mm.MongodManager.__init__
    monkeypatch.setattr(mm.MongodManager, "__init__",
                        lambda self, *a, **kw: orig(self, *a, **{**kw, "ping": False, "ready_timeout": 10}))
    mgr = de.start_local_mongod(data)
    try:
        assert _wait_dead(orphan.pid)
        assert mgr.is_running and mgr.pid != orphan.pid
    finally:
        de.stop_local_mongod(mgr, data)
