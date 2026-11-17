"""版本管理（客户端侧）：版本比较、更新检查各分支、426 / force 进入 update_required、白名单、请求体带版本字段。
全部用 httpx MockTransport 假服务，不联网、不需要 Mongo。"""
import json
import time

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core import license_client, license_config, license_keys, update_checker, version
from core.license_client import (
    LicenseClient, LicenseServerError, LicenseUpdateRequired, MemoryLicenseStore,
)
from core.license_guard import LicenseGuardMiddleware
from core.license_renewer import LicenseRenewer
from core.update_checker import UpdateChecker

from dongai_license import crypto, license_token

KID = "ktest"
COMPS = ["aaaaaaaaaaaaaaaa", "bbbbbbbbbbbbbbbb", "cccccccccccccccc"]
LATEST = {"version": "0.3.0", "notes": "修复若干问题", "url": "https://dl.example.com/DongAI-0.3.0.dmg",
          "sha256": "a" * 64, "size": 1234, "published_at": "2026-11-01T00:00:00Z"}


@pytest.fixture(autouse=True)
def env(monkeypatch, tmp_path):
    for k in ("DONGAI_DESKTOP", "DONGAI_LICENSE_ENFORCE", "DONGAI_LOCAL_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("DONGAI_DATA_DIR", str(tmp_path / "data"))
    update_checker.set_checker(None)
    yield
    update_checker.set_checker(None)
    license_client.set_client(None)


def checker(handler, cur="0.1.0", **kw):
    seen = []

    def h(request):
        seen.append(request)
        return handler(request)

    c = UpdateChecker(version_provider=lambda: cur, platform_provider=lambda: "mac-arm64",
                      channel_provider=lambda: "stable", url_provider=lambda: "https://lic.test/license/v1/update",
                      transport=httpx.MockTransport(h), **kw)
    c.seen = seen
    return c


def reply(body, status=200):
    return lambda request: httpx.Response(status, json=body)


# ---------------------------------------------------------------- version.py

@pytest.mark.parametrize("a,b,expected", [
    ("0.1.0", "0.1.0", 0), ("0.1.0", "0.1.1", -1), ("0.2.0", "0.1.9", 1), ("1.0.0", "0.99.99", 1),
    ("0.1.10", "0.1.9", 1), ("1.0.0-rc.1", "1.0.0", -1), ("1.0.0-rc.1", "1.0.0-rc.2", -1),
    ("1.0.0-rc.2", "1.0.0-rc.10", -1), ("1.0.0-alpha", "1.0.0-1", 1),
    ("0.1.0+testbuild", "0.1.0", 0), ("0.1.0+testbuild", "0.1.1", -1),
])
def test_compare_versions(a, b, expected):
    assert version.compare_versions(a, b) == expected
    assert version.compare_versions(b, a) == -expected


@pytest.mark.parametrize("bad", ["", "1", "1.2", "a.b.c", "1.2.3.4", "v1.2.3", None, 5])
def test_compare_versions_rejects_invalid(bad):
    assert version.is_valid_version(bad) is False
    with pytest.raises(ValueError):
        version.compare_versions(bad, "1.0.0")


def test_version_file_is_single_source():
    v = version.read_version_file()
    assert version.is_valid_version(v) and "+" not in v
    assert version.base_version() == v
    assert version.get_platform() in version.PLATFORMS + ("linux-x64",)
    assert version.get_channel() == "stable"
    assert license_config.APP_VERSION == version.get_version()


def test_test_build_marker_in_version(monkeypatch):
    monkeypatch.setattr(license_keys, "TEST_BUILD", True)
    assert version.get_version() == version.base_version() + "+testbuild"
    monkeypatch.setattr(license_keys, "TEST_BUILD", False)
    assert "+" not in version.get_version()


def test_build_meta_overrides(monkeypatch):
    import types
    meta = types.SimpleNamespace(VERSION="2.3.4", PLATFORM="win-x64", CHANNEL="beta")
    monkeypatch.setattr(version, "_bm", meta)
    assert (version.base_version(), version.get_platform(), version.get_channel()) == ("2.3.4", "win-x64", "beta")
    monkeypatch.setattr(version, "_bm", types.SimpleNamespace(VERSION="oops", PLATFORM="", CHANNEL="Bad Channel!"))
    assert version.base_version() == version.FALLBACK_VERSION and version.get_channel() == "stable"


# ---------------------------------------------------------------- update_checker 各分支

def test_check_sends_query_and_caches_available():
    c = checker(reply({"update_available": True, "latest": LATEST, "force": False, "min_supported": "0.1.0"}))
    snap = c.check()
    q = dict(c.seen[0].url.params)
    assert q == {"version": "0.1.0", "platform": "mac-arm64", "channel": "stable"}
    assert c.seen[0].method == "GET" and c.seen[0].url.path == "/license/v1/update"
    assert snap["update_available"] and snap["latest"]["version"] == "0.3.0" and snap["latest"]["sha256"] == "a" * 64
    assert not snap["force"] and not snap["update_required"] and not snap["check_failed"]
    assert snap["current_version"] == "0.1.0" and snap["checked_at"]
    assert c.snapshot() == snap            # status 接口读缓存，不联网
    assert len(c.seen) == 1


def test_check_no_update():
    c = checker(reply({"update_available": False, "latest": None, "force": False, "min_supported": None}))
    snap = c.check()
    assert snap["update_available"] is False and snap["latest"] is None and not snap["update_required"]


@pytest.mark.parametrize("handler", [
    lambda r: httpx.Response(500, text="boom"),
    lambda r: httpx.Response(404, json={}),
    lambda r: httpx.Response(200, text="<html>not json</html>"),
    lambda r: httpx.Response(200, json=["x"]),
    lambda r: httpx.Response(200, json={"latest": None}),
    lambda r: (_ for _ in ()).throw(httpx.ConnectError("down")),
])
def test_check_failure_is_silent_and_keeps_old_result(handler):
    ok = {"update_available": True, "latest": LATEST, "force": False, "min_supported": None}
    state = {"fail": False}
    c = checker(lambda r: handler(r) if state["fail"] else httpx.Response(200, json=ok))
    c.check()
    state["fail"] = True
    snap = c.check()          # 绝不抛异常
    assert snap["check_failed"] is True
    assert snap["update_available"] is True and snap["latest"]["version"] == "0.3.0"   # 旧结果保留
    assert not snap["update_required"]


def test_failure_never_triggers_update_required():
    c = checker(lambda r: httpx.Response(503))
    c.check()
    assert c.is_required() is False


def test_unsafe_download_url_is_dropped():
    bad = dict(LATEST, url="http://evil.example.com/a.dmg")
    c = checker(reply({"update_available": True, "latest": bad, "force": False, "min_supported": None}))
    assert c.check()["latest"]["url"] is None
    local = dict(LATEST, url="http://127.0.0.1:9000/a.dmg")
    c2 = checker(reply({"update_available": True, "latest": local, "force": False, "min_supported": None}))
    assert c2.check()["latest"]["url"] == "http://127.0.0.1:9000/a.dmg"   # 非桌面模式允许本机 http


def test_local_http_url_rejected_in_release_desktop(monkeypatch):
    monkeypatch.setenv("DONGAI_DESKTOP", "1")
    assert update_checker.download_url_allowed("http://127.0.0.1:9000/a.dmg") is False
    assert update_checker.download_url_allowed("https://dl.example.com/a.dmg") is True
    monkeypatch.setattr(license_keys, "TEST_BUILD", True)
    assert update_checker.download_url_allowed("http://127.0.0.1:9000/a.dmg") is True
    assert update_checker.download_url_allowed("http://evil.com/a.dmg") is False


def test_invalid_latest_version_ignored():
    c = checker(reply({"update_available": True, "latest": dict(LATEST, version="banana"), "force": False}))
    snap = c.check()
    assert snap["update_available"] is False and snap["latest"] is None


# ---------------------------------------------------------------- 强制升级：force / min_supported / 426

def test_force_true_requires_update_and_clears_after_upgrade():
    body = {"update_available": True, "latest": LATEST, "force": True, "min_supported": "0.2.0"}
    c = checker(reply(body))
    snap = c.check()
    assert snap["update_required"] and snap["force"] and c.is_required()
    # 升级到 0.3.0 后自动解除（纯本地比较）
    c._version = lambda: "0.3.0"
    assert not c.is_required()


def test_below_min_supported_requires_update_even_without_force():
    c = checker(reply({"update_available": True, "latest": LATEST, "force": False, "min_supported": "0.2.0"}))
    snap = c.check()
    assert snap["update_required"] and snap["min_supported"] == "0.2.0"


def test_check_result_no_longer_forcing_clears_required():
    state = {"force": True}
    c = checker(lambda r: httpx.Response(200, json={"update_available": True, "latest": LATEST,
                                                    "force": state["force"], "min_supported": None}))
    assert c.check()["update_required"]
    state["force"] = False
    assert not c.check()["update_required"]


def test_426_mark_survives_check_and_only_cleared_by_upgrade():
    c = checker(reply({"update_available": False, "latest": None, "force": False, "min_supported": None}))
    c.mark_required("0.2.0", "请升级")
    assert c.check()["update_required"]          # 更新检查说没事，也不能解除 426 来源的要求
    c._version = lambda: "0.2.0"
    assert not c.is_required()


def test_426_without_min_supported_is_per_version():
    c = checker(reply({}))
    c.mark_required("", "")
    assert c.is_required()
    c._version = lambda: "0.1.1"
    assert not c.is_required()


def test_required_state_persists_across_restart(tmp_path):
    f = tmp_path / "update_state.json"
    c1 = checker(reply({}), state_path=f)
    c1.mark_required("0.2.0", "请升级")
    c2 = checker(reply({}), state_path=f)
    assert c2.is_required() and c2.required_info()["min_supported"] == "0.2.0"
    f.write_text("{broken")
    assert checker(reply({}), state_path=f).is_required() is False   # 损坏文件当作没有，不崩


def test_non_desktop_does_not_touch_disk(tmp_path):
    c = checker(reply({}))
    c.mark_required("0.2.0", "")
    assert not (tmp_path / "data" / "update_state.json").exists()


# ---------------------------------------------------------------- 请求体带版本字段 + 426

def fake_server(keypair, captured, status_fn=None):
    priv, pub = keypair

    def handler(request: httpx.Request):
        body = json.loads(request.content)
        captured.append((request.url.path, body))
        if status_fn:
            r = status_fn(request.url.path, body)
            if r is not None:
                return r
        t = int(time.time())
        if request.url.path.endswith("/activate"):
            payload = license_token.verify_license(body["license_code"], {KID: pub}, body["machine_components"], now=t)
        else:
            payload = license_token.verify_lease(body["lease"], {KID: pub}, body["machine_components"], now=0)
        lexp = payload["exp"] if payload["typ"] == "license" else payload["lexp"]
        lease = license_token.issue_lease(priv, KID, lid=payload["lid"], mc=body["machine_components"],
                                          sid=payload.get("sid", "sid-1"), ttl_seconds=min(86400, lexp - t), iat=t,
                                          lexp=lexp, plan=payload["plan"], features=payload["features"],
                                          cv=1 if payload["typ"] == "license" else payload["cv"])
        return httpx.Response(200, json={"lease": lease, "expires_at": t + 3600, "server_time": t})
    return httpx.MockTransport(handler)


@pytest.fixture(scope="module")
def keypair():
    return crypto.generate_keypair()


def make_client(keypair, captured, status_fn=None):
    return LicenseClient(store=MemoryLicenseStore(), keys_provider=lambda: {KID: keypair[1]},
                         components_provider=lambda: list(COMPS), transport=fake_server(keypair, captured, status_fn),
                         server_url_provider=lambda: "https://lic.test",
                         app_version="0.1.0", platform="mac-arm64", channel="stable")


def code_for(keypair):
    return license_token.issue_license(keypair[0], KID, lid="lic_1", mc=COMPS, plan="pro", features=["video"],
                                       exp=int(time.time()) + 3600)


def test_activate_and_renew_bodies_carry_version_fields(keypair):
    captured = []
    c = make_client(keypair, captured)
    c.activate(code_for(keypair))
    c.renew()
    assert [p for p, _ in captured] == ["/license/v1/activate", "/license/v1/renew"]
    for _, body in captured:
        assert body["app_version"] == "0.1.0" and body["platform"] == "mac-arm64" and body["channel"] == "stable"


def test_default_client_info_uses_version_module(keypair):
    c = LicenseClient(store=MemoryLicenseStore())
    assert c._client_info() == {"app_version": version.get_version(), "platform": version.get_platform(),
                                "channel": version.get_channel()}


def upd426(path, body):
    return httpx.Response(426, json={"code": "UPDATE_REQUIRED", "message": "请升级", "min_supported": "0.2.0"})


def test_activate_426_enters_update_required(keypair):
    captured = []
    c = make_client(keypair, captured, upd426)
    with pytest.raises(LicenseUpdateRequired) as ei:
        c.activate(code_for(keypair))
    assert ei.value.min_supported == "0.2.0" and ei.value.status == 426
    assert update_checker.get_checker().is_required()
    assert c.status()["state"] == "unactivated"      # 授权状态本身不动


def test_renew_426_keeps_local_license_and_blocks_via_guard(keypair):
    flag = {"on": False}
    captured = []
    c = make_client(keypair, captured, lambda p, b: upd426(p, b) if flag["on"] else None)
    c.activate(code_for(keypair))
    flag["on"] = True
    with pytest.raises(LicenseServerError) as ei:
        c.renew()
    assert ei.value.code == "UPDATE_REQUIRED"
    assert c.status()["state"] == "valid"            # 租约原样保留（本地数据不动）
    assert c.store.read() is not None
    assert update_checker.get_checker().is_required()


def test_renewer_426_backs_off_one_hour(keypair):
    flag = {"on": True}
    t = [0.0]
    c2 = make_client(keypair, [], lambda p, b: upd426(p, b) if flag["on"] else None)
    flag["on"] = False
    c2.activate(code_for(keypair))
    flag["on"] = True
    r2 = LicenseRenewer(c2, monotonic=lambda: t[0], jitter=lambda a, b: a, interval=0)
    assert r2.run_once() == "rejected:UPDATE_REQUIRED"
    t[0] += 120
    assert r2.run_once() == "backoff"
    t[0] += 3600
    assert r2.run_once() == "rejected:UPDATE_REQUIRED"


# ---------------------------------------------------------------- 续租线程搭载更新检查

def test_renewer_runs_update_check_at_start_and_each_cycle(keypair):
    n = {"calls": 0}

    class FakeChecker:
        def check(self):
            n["calls"] += 1
            return {"check_failed": n.get("fail", False)}

    t = [0.0]
    c = make_client(keypair, [])
    r = LicenseRenewer(c, interval=100, monotonic=lambda: t[0], jitter=lambda a, b: a, update_checker=FakeChecker())
    r.run_once()
    assert n["calls"] == 1                      # 启动立即一次（即使未激活）
    t[0] = 50
    r.run_once()
    assert n["calls"] == 1                      # 周期内不重复
    t[0] = 101
    r.run_once()
    assert n["calls"] == 2                      # 每个续租周期一次
    n["fail"] = True
    t[0] = 300
    r.run_once()
    assert n["calls"] == 3
    t[0] = 301
    r.run_once()
    assert n["calls"] == 3                      # 失败后退避，不立刻重试


def test_renewer_survives_checker_exception(keypair):
    class Boom:
        def check(self):
            raise RuntimeError("x")

    c = make_client(keypair, [])
    r = LicenseRenewer(c, update_checker=Boom())
    assert r.run_once() in ("idle", "wait", "not_activated")   # 不抛异常


def test_renewer_without_checker_does_nothing(keypair):
    r = LicenseRenewer(make_client(keypair, []))
    assert r._update_checker is None
    r.run_once()


# ---------------------------------------------------------------- 守卫：update_required 完全拦截 + 白名单

def guard_client(monkeypatch):
    monkeypatch.setenv("DONGAI_LICENSE_ENFORCE", "1")
    from api import license as license_api
    from api import update as update_api
    app = FastAPI()
    app.include_router(license_api.router)
    app.include_router(update_api.router)

    @app.get("/api/projects")
    async def projects():
        return {"ok": True}

    @app.post("/api/projects")
    async def create():
        return {"ok": True}

    @app.get("/health")
    async def health():
        return {"status": "healthy"}

    @app.get("/")
    async def index():
        return {"page": "index"}

    app.add_middleware(LicenseGuardMiddleware)
    return TestClient(app)


def test_guard_blocks_everything_except_whitelist(monkeypatch):
    monkeypatch.setattr("core.license_guard._current_state", lambda: "valid")   # 授权有效也要拦
    c = UpdateChecker(version_provider=lambda: "0.1.0")
    update_checker.set_checker(c)
    http = guard_client(monkeypatch)
    assert http.get("/api/projects").status_code == 200       # 还没要求升级
    c.mark_required("0.2.0", "请升级")
    for method in ("get", "post"):
        r = getattr(http, method)("/api/projects")
        assert r.status_code == 403
        body = r.json()
        assert body["code"] == "UPDATE_REQUIRED" and body["state"] == "update_required"
        assert body["min_supported"] == "0.2.0" and body["message"]
    assert http.get("/health").status_code == 200
    assert http.get("/api/license/status").status_code == 200
    assert http.get("/api/license/machine-code").status_code in (200, 503)
    r = http.get("/api/update/status")
    assert r.status_code == 200 and r.json()["update_required"] is True
    assert http.get("/").status_code == 200                    # 非 /api 页面照常加载


def test_guard_websocket_closed_when_update_required(monkeypatch):
    monkeypatch.setattr("core.license_guard._current_state", lambda: "valid")
    c = UpdateChecker(version_provider=lambda: "0.1.0")
    c.mark_required("0.2.0", "")
    update_checker.set_checker(c)
    monkeypatch.setenv("DONGAI_LICENSE_ENFORCE", "1")
    from starlette.websockets import WebSocketDisconnect
    app = FastAPI()

    @app.websocket("/api/ws")
    async def ws(sock):
        await sock.accept()

    app.add_middleware(LicenseGuardMiddleware)
    with pytest.raises(WebSocketDisconnect):
        with TestClient(app).websocket_connect("/api/ws"):
            pass


def test_update_status_accessible_when_unactivated(monkeypatch):
    # 授权未激活：业务接口 403 LICENSE_REQUIRED，但 /api/update/status 放行
    update_checker.set_checker(UpdateChecker(version_provider=lambda: "0.1.0"))
    license_client.set_client(LicenseClient(store=MemoryLicenseStore(), components_provider=lambda: list(COMPS)))
    http = guard_client(monkeypatch)
    assert http.get("/api/projects").json()["code"] == "LICENSE_REQUIRED"
    r = http.get("/api/update/status")
    assert r.status_code == 200 and r.json()["current_version"] == "0.1.0"


def test_guard_enforcement_off_ignores_update_required():
    c = UpdateChecker(version_provider=lambda: "0.1.0")
    c.mark_required("0.2.0", "")
    update_checker.set_checker(c)
    app = FastAPI()

    @app.get("/api/x")
    async def x():
        return {"ok": 1}

    app.add_middleware(LicenseGuardMiddleware)
    assert TestClient(app).get("/api/x").status_code == 200    # 非桌面且未开启拦截时不影响现有测试/e2e


def test_exempt_paths():
    from core.license_guard import is_exempt
    for p in ("/api/update/status", "/api/update/check", "/api/license/status", "/health"):
        assert is_exempt({"type": "http", "method": "GET", "path": p})
    assert not is_exempt({"type": "http", "method": "GET", "path": "/api/updates"})
    assert not is_exempt({"type": "http", "method": "GET", "path": "/api/projects"})


# ---------------------------------------------------------------- API

def test_activate_endpoint_maps_426(keypair, monkeypatch):
    from api import license as license_api
    app = FastAPI()
    app.include_router(license_api.router)
    license_client.set_client(make_client(keypair, [], upd426))
    monkeypatch.setattr(license_client, "get_machine_components", lambda: list(COMPS))
    r = TestClient(app).post("/api/license/activate", json={"code": code_for(keypair)})
    assert r.status_code == 426
    assert r.json()["code"] == "UPDATE_REQUIRED" and r.json()["min_supported"] == "0.2.0"


def test_update_check_endpoint_and_rate_limit(monkeypatch):
    from api import update as update_api
    update_api._check_limiter.__init__(3, 60.0)
    c = checker(reply({"update_available": True, "latest": LATEST, "force": False, "min_supported": None}))
    update_checker.set_checker(c)
    app = FastAPI()
    app.include_router(update_api.router)
    http = TestClient(app)
    assert http.get("/api/update/status").json()["update_available"] is False   # 还没检查过
    r = http.post("/api/update/check")
    assert r.status_code == 200 and r.json()["update_available"] is True
    assert http.get("/api/update/status").json()["latest"]["version"] == "0.3.0"
    http.post("/api/update/check")
    http.post("/api/update/check")
    assert http.post("/api/update/check").status_code == 429


def test_build_info_has_version_fields():
    import desktop_entry
    info = desktop_entry.build_info()
    assert info["version"] == version.base_version() and info["app_version"] == version.get_version()
    assert info["platform"] == version.get_platform() and info["channel"] == version.get_channel()
    assert "test_build" in info and "kids" in info


# ---------------------------------------------------------------- 版本单一来源：VERSION ↔ Electron 壳 package.json

def _sync_module():
    import importlib.util
    from config import paths
    spec = importlib.util.spec_from_file_location("sync_version", paths.REPO_ROOT / "desktop" / "sync_version.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_repo_version_matches_shell_package():
    sv = _sync_module()
    assert sv.check_consistent() == version.base_version()


def test_sync_version_writes_and_check_fails_on_mismatch(tmp_path):
    sv = _sync_module()
    (tmp_path / "VERSION").write_text("1.2.3\n")
    pkg = tmp_path / "package.json"
    lock = tmp_path / "package-lock.json"
    pkg.write_text(json.dumps({"name": "x", "version": "0.1.0"}))
    lock.write_text(json.dumps({"name": "x", "version": "0.1.0", "packages": {"": {"version": "0.1.0"}}}))
    with pytest.raises(SystemExit) as ei:
        sv.check_consistent(tmp_path / "VERSION", pkg)
    assert "不一致" in str(ei.value)
    assert sv.sync_shell_version("1.2.3", pkg, lock) is True
    assert json.loads(pkg.read_text())["version"] == "1.2.3"
    assert json.loads(lock.read_text())["packages"][""]["version"] == "1.2.3"
    assert sv.check_consistent(tmp_path / "VERSION", pkg) == "1.2.3"
    assert sv.sync_shell_version("1.2.3", pkg, lock) is False      # 幂等


@pytest.mark.parametrize("bad", ["", "1.2", "1.2.3+testbuild", "latest"])
def test_version_file_must_be_plain_semver(tmp_path, bad):
    sv = _sync_module()
    (tmp_path / "VERSION").write_text(bad + "\n")
    with pytest.raises(SystemExit):
        sv.read_version(tmp_path / "VERSION")
