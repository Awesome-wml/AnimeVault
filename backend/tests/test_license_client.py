"""L-26 客户端授权：license_client、/api/license 接口、全局拦截中间件。不需要 Mongo。

L-41 起激活必须联网换租约：这里用 FakeLicenseServer（进程内的 httpx MockTransport，签发真实租约）代替授权服务，
真实服务端的集成测试见 test_license_renew.py。
"""
import asyncio
import json
import os
import stat
import time

import httpx
import pytest
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient

from config import paths
from core import license_client, license_guard, license_keys
from core.license_client import FileLicenseStore, LicenseClient, LicenseStore, MemoryLicenseStore
from core.license_guard import LicenseGuardMiddleware
from core.local_token import LocalTokenMiddleware

import dongai_license
from dongai_license import crypto, license_token, machine_code

KID = "ktest"
MY_COMPS = ["aaaaaaaaaaaaaaaa", "bbbbbbbbbbbbbbbb", "cccccccccccccccc"]
OTHER_COMPS = ["1111111111111111", "2222222222222222", "3333333333333333"]


@pytest.fixture(scope="module")
def keypair():
    return crypto.generate_keypair()


def fake_license_server(keypair, now=time.time, down=False):
    """最小的授权服务替身：校验授权码后签发真实租约（有效期不超过授权到期时间）。"""
    priv, pub = keypair

    def handler(request: httpx.Request):
        if down:
            raise httpx.ConnectError("down", request=request)
        body = json.loads(request.content)
        if request.url.path.endswith("/activate"):
            payload = license_token.verify_license(body["license_code"], {KID: pub}, body["machine_components"], now=now())
        else:
            payload = license_token.verify_lease(body["lease"], {KID: pub}, body["machine_components"], now=0)
        t = int(now())
        ttl = min(86400, payload["exp"] - t) if "plan" in payload else 86400
        lid = payload["lid"]
        exp = payload["exp"] if "plan" in payload else t + 86400
        lease = license_token.issue_lease(priv, KID, lid=lid, mc=body["machine_components"],
                                          sid=payload.get("sid", "sid-1"), ttl_seconds=ttl, iat=t)
        return httpx.Response(200, json={"lease": lease, "expires_at": t + ttl, "server_time": t,
                                         "license": {"plan": "pro", "features": ["video"], "expires_at": exp,
                                                     "status": "active"}})
    return httpx.MockTransport(handler)


@pytest.fixture(autouse=True)
def env(monkeypatch, tmp_path, keypair):
    for k in ("DONGAI_DESKTOP", "DONGAI_LICENSE_ENFORCE", "DONGAI_LOCAL_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("DONGAI_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("DONGAI_LICENSE_DEV", "1")
    monkeypatch.setenv("DONGAI_LICENSE_PUBKEYS", json.dumps({KID: keypair[1]}))
    monkeypatch.setattr(license_client, "get_machine_components", lambda: list(MY_COMPS))
    client = LicenseClient(components_provider=lambda: list(MY_COMPS), transport=fake_license_server(keypair))
    license_client.set_client(client)
    yield client
    license_client.set_client(None)


def make_code(keypair, mc=None, exp_delta=3600, plan="pro", kid=KID):
    return license_token.issue_license(
        keypair[0], kid, lid="lic_1", mc=mc or MY_COMPS, plan=plan,
        features=["video"], exp=int(time.time()) + exp_delta)


def build_app():
    app = FastAPI()
    from api import license as license_api
    app.include_router(license_api.router)

    @app.get("/api/projects")
    async def projects():
        return {"ok": True}

    @app.get("/health")
    async def health():
        return {"status": "healthy"}

    @app.get("/api/stream")
    async def stream():
        async def gen():
            yield "data: 1\n\n"
        return StreamingResponse(gen(), media_type="text/event-stream")

    app.add_middleware(LicenseGuardMiddleware)
    app.add_middleware(LocalTokenMiddleware)
    return app


@pytest.fixture
def http():
    return TestClient(build_app())


# ---------------------------------------------------------------- license_client

def test_unactivated(env):
    s = env.status()
    assert s["state"] == "unactivated" and s["plan"] is None and s["expires_at"] is None
    assert s["machine_code"] == machine_code.format_machine_code(MY_COMPS)


def test_activate_success_and_status(env, keypair):
    code = make_code(keypair)
    res = env.activate(code)
    assert res["state"] == "valid" and res["plan"] == "pro" and res["features"] == ["video"]
    s = env.status()
    assert s["state"] == "valid" and s["expires_at"] > time.time()
    assert env.store.read() == code
    env.deactivate()
    assert env.status()["state"] == "unactivated"


def test_machine_mismatch(env, keypair):
    code = make_code(keypair, mc=OTHER_COMPS)
    with pytest.raises(license_token.MachineMismatch):
        env.activate(code)
    assert env.store.read() is None
    # 已保存的授权后来分量变了（比如换机拷贝文件）
    env.store.write(code)
    assert env.status()["state"] == "machine_mismatch"


def test_expired(env, keypair):
    code = make_code(keypair, exp_delta=-10)
    with pytest.raises(license_token.LicenseExpired):
        env.activate(code)
    # L-41：只有授权码、没有租约的老格式存储不放行，要求联网重新激活（授权到期的状态见 test_status_not_cached...）
    env.store.write(code)
    assert env.status()["state"] == "unactivated" and env.status()["needs_online"] is True


def test_tampered_and_garbage(env, keypair):
    code = make_code(keypair)
    body, sig = code.split(".")
    flipped = ("B" if body[10] != "B" else "C")
    tampered = body[:10] + flipped + body[11:] + "." + sig
    for bad in (tampered, "not a code", "", "AAAA.BBBB"):
        with pytest.raises(license_token.LicenseInvalid):
            env.activate(bad)
    assert env.store.read() is None
    env.store.write(tampered)
    assert env.status()["state"] == "invalid"


def test_unknown_kid_is_invalid(env, keypair):
    code = make_code(keypair, kid="other")
    with pytest.raises(license_token.LicenseInvalid):
        env.activate(code)


def test_display_format_paste(env, keypair):
    code = make_code(keypair)
    shown = license_token.format_for_display(code)
    assert "\n" in shown and "-" in shown
    for text in (shown, shown.lower(), "  " + shown.replace("\n", "\r\n") + "\n\n", shown.replace("-", " - ")):
        env.deactivate()
        assert env.activate(text)["state"] == "valid"
        assert env.store.read() == code  # 保存的是规范化后的原码


def test_status_not_cached_expiry_checked_each_time(keypair):
    now = [time.time()]
    store = _MemStore()
    c = LicenseClient(store=store, components_provider=lambda: list(MY_COMPS), clock=lambda: now[0],
                      transport=fake_license_server(keypair, now=lambda: now[0]))
    code = license_token.issue_license(keypair[0], KID, lid="l", mc=MY_COMPS, plan="pro",
                                       features=[], exp=int(now[0]) + 100)
    c.activate(code)
    assert c.status()["state"] == "valid"
    now[0] += 101
    assert c.status()["state"] == "expired"


class _MemStore(MemoryLicenseStore):
    def __init__(self, fail=False):
        super().__init__()
        self.fail = fail

    def read(self):
        if self.fail:
            raise OSError("boom")
        return super().read()


def test_store_read_error_is_invalid_not_exception():
    c = LicenseClient(store=_MemStore(fail=True), components_provider=lambda: list(MY_COMPS))
    assert c.status()["state"] == "invalid"


# ---------------------------------------------------------------- 公钥来源

def test_env_pubkeys_override_only_in_dev_non_desktop(monkeypatch, keypair):
    assert license_client.get_public_keys() == {KID: keypair[1]}
    # 桌面模式一律忽略
    monkeypatch.setenv("DONGAI_DESKTOP", "1")
    assert license_client.get_public_keys() == license_keys.PUBLIC_KEYS
    monkeypatch.delenv("DONGAI_DESKTOP")
    # 没开 DEV 也忽略
    monkeypatch.delenv("DONGAI_LICENSE_DEV")
    assert license_client.get_public_keys() == license_keys.PUBLIC_KEYS
    # DEV 开了但 JSON 坏了：忽略
    monkeypatch.setenv("DONGAI_LICENSE_DEV", "1")
    monkeypatch.setenv("DONGAI_LICENSE_PUBKEYS", "{bad")
    assert license_client.get_public_keys() == license_keys.PUBLIC_KEYS


def test_desktop_mode_rejects_code_signed_by_env_key(env, keypair, monkeypatch):
    code = make_code(keypair)
    monkeypatch.setenv("DONGAI_DESKTOP", "1")
    c = LicenseClient(store=_MemStore(), components_provider=lambda: list(MY_COMPS),
                      transport=fake_license_server(keypair))
    with pytest.raises(license_token.LicenseInvalid):
        c.activate(code)


def test_placeholder_key_present():
    assert license_keys.PUBLIC_KEYS


# ---------------------------------------------------------------- 存储

@pytest.mark.skipif(os.name == "nt", reason="POSIX 权限")
def test_file_store_permissions_and_roundtrip(tmp_path):
    store = FileLicenseStore()
    assert store.read() is None
    store.write("ABC")
    f = paths.license_file()
    assert f == tmp_path / "data" / "license" / "license.json"
    assert stat.S_IMODE(f.stat().st_mode) == 0o600
    assert stat.S_IMODE(f.parent.stat().st_mode) == 0o700
    assert store.read() == "ABC"
    store.write("DEF")  # 覆盖后权限仍是 600
    assert stat.S_IMODE(f.stat().st_mode) == 0o600 and store.read() == "DEF"
    assert store.read_lease() is None  # 老格式：没有租约记录
    store.write("DEF", {"lease": "L", "server_time": 1})
    assert stat.S_IMODE(f.stat().st_mode) == 0o600 and store.read_lease() == {"lease": "L", "server_time": 1}
    store.write_lease({"lease": "M"})  # 只换租约，授权码保留
    assert store.read() == "DEF" and store.read_lease() == {"lease": "M"}
    store.write(None, {"block": "revoked"})  # 只留状态标记
    assert store.read() is None and store.read_lease() == {"block": "revoked"}
    store.clear()
    assert not f.exists() and store.read() is None
    store.clear()  # 重复清除不报错


def test_file_store_corrupt_file_raises(tmp_path):
    store = FileLicenseStore()
    store.write("X")
    paths.license_file().write_text("{not json")
    with pytest.raises(Exception):
        store.read()


# ---------------------------------------------------------------- /api/license 接口

def test_api_machine_code_and_status(http):
    r = http.get("/api/license/machine-code")
    assert r.status_code == 200
    j = r.json()
    assert j["machine_code"] == machine_code.format_machine_code(MY_COMPS)
    assert "-".join(j["groups"]) == j["machine_code"]
    assert http.get("/api/license/status").json()["state"] == "unactivated"


def test_api_activate_flow_and_errors(http, keypair):
    r = http.post("/api/license/activate", json={"code": "garbage"})
    assert r.status_code == 400 and r.json()["code"] == "LICENSE_INVALID"
    assert "kid" not in r.text.lower()
    r = http.post("/api/license/activate", json={"code": make_code(keypair, mc=OTHER_COMPS)})
    assert r.status_code == 403 and r.json()["code"] == "LICENSE_MACHINE_MISMATCH"
    r = http.post("/api/license/activate", json={"code": make_code(keypair, exp_delta=-5)})
    assert r.status_code == 403 and r.json()["code"] == "LICENSE_EXPIRED"
    assert all(x["message"] for x in [r.json()])
    shown = license_token.format_for_display(make_code(keypair))
    r = http.post("/api/license/activate", json={"code": shown})
    assert r.status_code == 200 and r.json()["state"] == "valid" and r.json()["plan"] == "pro"
    assert http.get("/api/license/status").json()["state"] == "valid"
    r = http.post("/api/license/deactivate")
    assert r.status_code == 200 and r.json()["state"] == "unactivated"


def test_api_activate_empty_body(http):
    r = http.post("/api/license/activate", json={})
    assert r.status_code == 400 and r.json()["code"] == "LICENSE_INVALID"


# ---------------------------------------------------------------- 拦截中间件

def test_non_desktop_default_not_enforced(http):
    assert http.get("/api/projects").status_code == 200


def test_enforce_env_blocks_and_exemptions(http, monkeypatch, keypair):
    monkeypatch.setenv("DONGAI_LICENSE_ENFORCE", "1")
    r = http.get("/api/projects")
    assert r.status_code == 403
    j = r.json()
    assert j["code"] == "LICENSE_REQUIRED" and j["state"] == "unactivated" and j["message"]
    assert http.get("/health").status_code == 200
    assert http.get("/api/license/status").status_code == 200
    assert http.options("/api/projects").status_code != 403
    assert http.get("/docs").status_code == 200
    assert http.get("/openapi.json").status_code == 200
    # 授权后放行
    assert http.post("/api/license/activate", json={"code": make_code(keypair)}).status_code == 200
    assert http.get("/api/projects").status_code == 200
    # 注销后再次拦截
    http.post("/api/license/deactivate")
    assert http.get("/api/projects").status_code == 403


def test_blocked_path_lookalikes(http, monkeypatch):
    monkeypatch.setenv("DONGAI_LICENSE_ENFORCE", "1")
    for p in ("/api/licensex/status", "/health/../api/projects", "/staticfoo", "/api/projects?x=/static/"):
        assert http.get(p).status_code in (403, 404), p
    assert http.get("/api/licensex/status").status_code == 403


def test_desktop_mode_enforces_and_env_cannot_disable(http, monkeypatch):
    monkeypatch.setenv("DONGAI_DESKTOP", "1")
    assert http.get("/api/projects").status_code == 403
    monkeypatch.setenv("DONGAI_LICENSE_ENFORCE", "0")
    assert http.get("/api/projects").status_code == 403
    monkeypatch.setenv("DONGAI_LICENSE_ENFORCE", "")
    assert http.get("/api/projects").status_code == 403
    assert http.get("/health").status_code == 200


def test_fail_closed_when_status_raises(http, monkeypatch):
    monkeypatch.setenv("DONGAI_LICENSE_ENFORCE", "1")

    def boom():
        raise RuntimeError("x")
    monkeypatch.setattr(license_client, "get_client", boom)
    r = http.get("/api/projects")
    assert r.status_code == 403 and r.json()["code"] == "LICENSE_REQUIRED" and r.json()["state"] == "invalid"


def test_fail_closed_when_store_read_fails(http, monkeypatch):
    monkeypatch.setenv("DONGAI_LICENSE_ENFORCE", "1")
    license_client.set_client(LicenseClient(store=_MemStore(fail=True), components_provider=lambda: list(MY_COMPS)))
    assert http.get("/api/projects").status_code == 403


def test_fail_closed_when_enforcement_check_raises(http, monkeypatch):
    def boom():
        raise RuntimeError("x")
    monkeypatch.setattr(license_guard, "enforcement_enabled", boom)
    assert http.get("/api/projects").status_code == 403


def test_local_token_runs_before_license(monkeypatch):
    monkeypatch.setenv("DONGAI_LICENSE_ENFORCE", "1")
    monkeypatch.setenv("DONGAI_LOCAL_TOKEN", "tok")
    c = TestClient(build_app())
    assert c.get("/api/projects").status_code == 401                       # 令牌先拒
    r = c.get("/api/projects", headers={"X-DongAI-Local-Token": "tok"})
    assert r.status_code == 403 and r.json()["code"] == "LICENSE_REQUIRED"  # 令牌过了再看授权
    assert c.get("/api/license/status", headers={"X-DongAI-Local-Token": "tok"}).status_code == 200


def test_sse_not_buffered_when_licensed(env, keypair):
    """已授权时，流式响应的第一块要在应用结束之前就送出（中间件不能缓冲）。"""
    env.activate(make_code(keypair))
    os.environ["DONGAI_LICENSE_ENFORCE"] = "1"
    try:
        gate = asyncio.Event()
        order = []

        async def app(scope, receive, send):
            await send({"type": "http.response.start", "status": 200,
                        "headers": [(b"content-type", b"text/event-stream")]})
            await send({"type": "http.response.body", "body": b"data: 1\n\n", "more_body": True})
            await gate.wait()
            await send({"type": "http.response.body", "body": b"data: 2\n\n"})

        mw = LicenseGuardMiddleware(app)
        sent = []

        async def send(msg):
            sent.append(msg)
            if msg["type"] == "http.response.body" and msg.get("body") == b"data: 1\n\n":
                order.append("first_chunk_seen")

        async def run():
            scope = {"type": "http", "method": "POST", "path": "/api/novel/generate", "headers": []}
            task = asyncio.create_task(mw(scope, None, send))
            for _ in range(50):
                if order:
                    break
                await asyncio.sleep(0.01)
            assert order == ["first_chunk_seen"] and not task.done()
            gate.set()
            await task

        asyncio.run(run())
        assert sent[-1]["body"] == b"data: 2\n\n"
    finally:
        os.environ.pop("DONGAI_LICENSE_ENFORCE", None)


def test_streaming_route_through_full_stack(http, monkeypatch, keypair):
    monkeypatch.setenv("DONGAI_LICENSE_ENFORCE", "1")
    assert http.get("/api/stream").status_code == 403
    http.post("/api/license/activate", json={"code": make_code(keypair)})
    with http.stream("GET", "/api/stream") as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        assert "".join(r.iter_text()) == "data: 1\n\n"


def test_websocket_blocked_when_unlicensed(monkeypatch):
    monkeypatch.setenv("DONGAI_LICENSE_ENFORCE", "1")
    app = build_app()

    @app.websocket("/ws")
    async def ws(websocket):
        await websocket.accept()
        await websocket.send_text("hi")

    c = TestClient(app)
    from starlette.websockets import WebSocketDisconnect
    with pytest.raises(WebSocketDisconnect):
        with c.websocket_connect("/ws"):
            pass
