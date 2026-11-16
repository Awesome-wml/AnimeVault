"""L-06 后端同源提供前端页面：挂载、SPA 回落、API 不被覆盖、令牌与授权放行规则。"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core import frontend_mount, license_guard
from core.license_guard import LicenseGuardMiddleware, is_exempt
from core.local_token import LocalTokenMiddleware


@pytest.fixture
def dist(tmp_path):
    d = tmp_path / "dist"
    (d / "js").mkdir(parents=True)
    (d / "index.html").write_text("<html>INDEX</html>", encoding="utf-8")
    (d / "js" / "app.js").write_text("console.log(1)", encoding="utf-8")
    (d / "favicon.ico").write_bytes(b"ico")
    (tmp_path / "secret.txt").write_text("SECRET", encoding="utf-8")
    return d


def build_app():
    app = FastAPI()

    @app.get("/")
    async def root():
        return {"app": "json-root"}

    @app.get("/health")
    async def health():
        return {"status": "healthy"}

    @app.get("/api/ping")
    async def ping():
        return {"pong": True}

    @app.get("/api/license/status")
    async def lic():
        return {"state": "none"}

    frontend_mount.mount_frontend(app)
    app.add_middleware(LicenseGuardMiddleware)
    app.add_middleware(LocalTokenMiddleware)
    return app


@pytest.fixture
def env(monkeypatch):
    for k in ("DONGAI_FRONTEND_DIR", "DONGAI_DESKTOP", "DONGAI_LOCAL_TOKEN", "DONGAI_LICENSE_ENFORCE"):
        monkeypatch.delenv(k, raising=False)
    return monkeypatch


def test_not_mounted_without_env(env):
    c = TestClient(build_app())
    assert c.get("/").json() == {"app": "json-root"}
    assert c.get("/js/app.js").status_code == 404


def test_not_mounted_when_dir_has_no_index(env, tmp_path):
    env.setenv("DONGAI_FRONTEND_DIR", str(tmp_path))
    c = TestClient(build_app())
    assert c.get("/").json() == {"app": "json-root"}


def test_mounted_serves_index_assets_and_fallback(env, dist):
    env.setenv("DONGAI_FRONTEND_DIR", str(dist))
    c = TestClient(build_app())
    r = c.get("/")
    assert r.status_code == 200 and "INDEX" in r.text
    assert c.get("/js/app.js").text == "console.log(1)"
    assert c.get("/favicon.ico").content == b"ico"
    assert "INDEX" in c.get("/projects/123/shots").text  # 前端路由回落
    assert c.get("/js/missing.js").status_code == 404  # 带扩展名的缺失文件不回落
    assert "SECRET" not in c.get("/../secret.txt").text  # 不能读到 dist 之外


def test_backend_paths_not_overridden(env, dist):
    env.setenv("DONGAI_FRONTEND_DIR", str(dist))
    c = TestClient(build_app())
    assert c.get("/health").json() == {"status": "healthy"}
    assert c.get("/api/ping").json() == {"pong": True}
    for p in ("/api/nope", "/static/nope.png", "/static/nope", "/docs/x"):
        r = c.get(p)
        assert r.status_code == 404 and "INDEX" not in r.text, p


def test_frontend_needs_no_token_but_api_does(env, dist):
    env.setenv("DONGAI_FRONTEND_DIR", str(dist))
    env.setenv("DONGAI_LOCAL_TOKEN", "tok")
    c = TestClient(build_app())
    assert c.get("/").status_code == 200
    assert c.get("/js/app.js").status_code == 200
    assert c.get("/some/route").status_code == 200
    assert c.get("/api/ping").status_code == 401
    assert c.get("/api/ping", headers={"X-DongAI-Local-Token": "tok"}).status_code == 200


def test_license_guard_only_blocks_api(env, dist):
    env.setenv("DONGAI_FRONTEND_DIR", str(dist))
    env.setenv("DONGAI_DESKTOP", "1")
    env.setattr(license_guard, "_current_state", lambda: "none")
    c = TestClient(build_app())
    assert c.get("/").status_code == 200
    assert c.get("/js/app.js").status_code == 200
    assert c.get("/health").status_code == 200
    r = c.get("/api/ping")
    assert r.status_code == 403 and r.json()["code"] == "LICENSE_REQUIRED"
    assert c.get("/api/license/status").status_code == 200


def test_is_exempt_rules():
    def http(p, m="GET"):
        return {"type": "http", "path": p, "method": m}

    assert is_exempt(http("/"))
    assert is_exempt(http("/js/app.js"))
    assert is_exempt(http("/projects/1"))
    assert not is_exempt(http("/api/projects"))
    assert not is_exempt(http("/api"))
    assert not is_exempt(http("/api/licensefoo"))
    assert is_exempt(http("/api/license/status"))
    assert not is_exempt({"type": "websocket", "path": "/ws/x"})  # websocket 不享受「非 /api 放行」
