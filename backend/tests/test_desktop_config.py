"""L-03 桌面模式配置：数据目录推导、JWT 自动生成、本地令牌中间件。"""
import importlib
import os
import stat
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from config import paths
from core.local_token import LocalTokenMiddleware


@pytest.fixture
def clean_env(monkeypatch):
    for k in ("DONGAI_DESKTOP", "DONGAI_DATA_DIR", "DONGAI_LOCAL_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    return monkeypatch


def test_not_desktop_paths_unchanged(clean_env):
    assert not paths.is_desktop()
    assert paths.log_file() == paths.BACKEND_DIR / "backend.log"
    assert paths.project_root() == paths.REPO_ROOT
    assert paths.doubao_accounts_json() == paths.REPO_ROOT / "doubao_accounts.json"
    assert paths.jianying_template_dir() == paths.BACKEND_DIR / ".jianying_template"


def test_data_dir_from_env_and_derived_paths(clean_env, tmp_path):
    clean_env.setenv("DONGAI_DESKTOP", "1")
    clean_env.setenv("DONGAI_DATA_DIR", str(tmp_path / "data"))
    assert paths.is_desktop()
    assert paths.data_dir() == tmp_path / "data"
    assert paths.static_dir_default() == tmp_path / "data" / "static"
    assert paths.log_file() == tmp_path / "data" / "logs" / "backend.log"
    assert paths.project_root() == tmp_path / "data"
    assert paths.doubao_accounts_json() == tmp_path / "data" / "doubao_accounts.json"
    assert paths.jianying_template_dir() == tmp_path / "data" / "jianying_template"


def test_default_data_dir_per_platform(clean_env, monkeypatch, tmp_path):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(sys, "platform", "darwin")
    assert paths.data_dir() == tmp_path / "Library/Application Support/DongAI"
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    assert paths.data_dir() == tmp_path / "Roaming" / "DongAI"
    monkeypatch.setattr(sys, "platform", "linux")
    assert paths.data_dir() == tmp_path / ".local/share/DongAI"


def test_jwt_secret_generated_persisted_and_600(clean_env, tmp_path):
    clean_env.setenv("DONGAI_DATA_DIR", str(tmp_path))
    first = paths.load_or_create_jwt_secret()
    assert len(first) >= 32
    f = paths.jwt_secret_file()
    assert f == tmp_path / "secrets" / "jwt.secret"
    if os.name != "nt":
        assert stat.S_IMODE(f.stat().st_mode) == 0o600
    assert paths.load_or_create_jwt_secret() == first


def _reload_settings():
    import config.settings as st
    return importlib.reload(st).settings


def test_settings_desktop_defaults_and_second_start_same_secret(clean_env, tmp_path):
    clean_env.setenv("DONGAI_DESKTOP", "1")
    clean_env.setenv("DONGAI_DATA_DIR", str(tmp_path))
    clean_env.delenv("STATIC_DIR", raising=False)
    clean_env.delenv("JWT_SECRET", raising=False)
    try:
        s1 = _reload_settings()
        assert s1.STATIC_DIR == str(tmp_path / "static")
        assert s1.JWT_SECRET != "your-secret-key-please-change-this"
        s2 = _reload_settings()
        assert s2.JWT_SECRET == s1.JWT_SECRET
        clean_env.setenv("JWT_SECRET", "explicit")
        assert _reload_settings().JWT_SECRET == "explicit"
    finally:
        clean_env.undo()
        _reload_settings()


def test_settings_not_desktop_keeps_defaults(clean_env):
    clean_env.delenv("STATIC_DIR", raising=False)
    try:
        s = _reload_settings()
        assert s.STATIC_DIR in ("../static",) or os.environ.get("STATIC_DIR") is None
    finally:
        clean_env.undo()
        _reload_settings()


def _app():
    app = FastAPI()
    app.add_middleware(LocalTokenMiddleware)

    @app.get("/api/x")
    def x():
        return {"ok": 1}

    @app.options("/api/x")
    def xo():
        return {}

    @app.get("/health")
    def h():
        return {"ok": 1}

    @app.get("/static/a.txt")
    def st():
        return {"ok": 1}

    return TestClient(app)


def test_token_middleware_inactive_without_env(clean_env):
    assert _app().get("/api/x").status_code == 200


def test_token_middleware_enforced(clean_env):
    clean_env.setenv("DONGAI_LOCAL_TOKEN", "tok123")
    c = _app()
    assert c.get("/api/x").status_code == 401
    assert c.get("/api/x", headers={"X-DongAI-Local-Token": "bad"}).status_code == 401
    assert c.get("/api/x", headers={"X-DongAI-Local-Token": "tok123"}).status_code == 200
    for ok in ("/health", "/static/a.txt"):
        assert c.get(ok).status_code == 200
    assert c.options("/api/x").status_code == 200


def test_token_only_accepted_via_header_not_query(clean_env):
    """EventSource/下载已改成 fetch 带请求头；查询参数里的令牌（任何名字）都不能放行 /api/*。"""
    clean_env.setenv("DONGAI_LOCAL_TOKEN", "secret")
    c = _app()
    for q in ("_lt=secret", "token=secret", "local_token=secret"):
        assert c.get(f"/api/x?{q}").status_code == 401
    assert c.get("/api/x", headers={"X-DongAI-Local-Token": "secret"}).status_code == 200
