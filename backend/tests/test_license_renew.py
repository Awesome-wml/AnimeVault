"""L-41 客户端在线租约：把客户端经 httpx MockTransport 接到真实的授权服务应用（license-server，内存仓库）上做集成测试。

不 sleep：时间全部由注入的时钟推进（墙钟/单调时钟/服务端时钟三者独立，可单独拨动墙钟模拟回拨）。
导入不到授权服务（仓库里没有 ../license-server）时整个文件跳过。
"""
import asyncio
import json
import logging
import sys
import threading
import time
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from config import paths
from core import license_client, license_config, license_renewer
from core.license_client import (
    GRACE_SECONDS, FileLicenseStore, LicenseClient, LicenseServerError, LicenseServerUnreachable,
    MemoryLicenseStore, NotActivated,
)
from core.license_guard import LicenseGuardMiddleware
from core.license_renewer import LicenseRenewer
from dongai_license import crypto, license_token
from dongai_license.machine_code import format_machine_code

_SERVER_DIR = Path(__file__).resolve().parents[2] / "license-server"
# 只在导入期间把 license-server 放进 sys.path：它自带 tests 包，长期留在路径里会遮住 backend/tests。
_added = str(_SERVER_DIR) not in sys.path
try:
    if _added:
        sys.path.append(str(_SERVER_DIR))
    from app.config import DbSettings, Settings  # noqa: E402
    from app.create_admin import create_admin_in_repo  # noqa: E402
    from app.main import create_app as create_server_app  # noqa: E402
    from app.repo.memory import make_memory_repos  # noqa: E402
except Exception as _e:  # pragma: no cover
    pytest.skip(f"无法导入 license-server：{_e}", allow_module_level=True)
finally:
    if _added and str(_SERVER_DIR) in sys.path:
        sys.path.remove(str(_SERVER_DIR))

MY_COMPS = ["aaaaaaaaaaaaaaaa", "bbbbbbbbbbbbbbbb", "cccccccccccccccc"]
BASE = "https://license.example.com"
ADMIN_PW = "correct horse battery"
HOUR, DAY = 3600, 86400


class FakeTime:
    """三个独立的时间源：服务端时间、客户端墙钟（= 服务端时间 + skew）、客户端单调时钟。"""

    def __init__(self):
        self.srv = float(int(time.time()))
        self.skew = 0.0
        self.m = 1000.0

    def wall(self):
        return self.srv + self.skew

    def mono(self):
        return self.m

    def server(self):
        return self.srv

    def advance(self, seconds):
        self.srv += seconds
        self.m += seconds

    def jump_wall(self, delta):
        """只拨墙钟（回拨/快进系统时间），不影响服务端时间和单调时钟。"""
        self.skew += delta


class Net:
    """客户端 -> 授权服务的传输层：转发到 TestClient，可模拟断网和固定响应。"""

    def __init__(self, tc):
        self.tc = tc
        self.down = False
        self.force = None  # (status, json)
        self.mutate = None  # 对真实响应 JSON 做就地改动（模拟中间人改写未签名字段）
        self.calls = []

    def handler(self, request: httpx.Request):
        self.calls.append(request.url.path)
        if self.down:
            raise httpx.ConnectError("down", request=request)
        if self.force:
            return httpx.Response(self.force[0], json=self.force[1])
        headers = {k: v for k, v in request.headers.items()
                   if k in ("content-type", "authorization", "x-machine-components")}
        r = self.tc.request(request.method, request.url.path, content=request.content, headers=headers)
        if self.mutate and r.status_code == 200:
            j = r.json()
            self.mutate(j)
            return httpx.Response(200, json=j)
        return httpx.Response(r.status_code, content=r.content,
                              headers={"content-type": r.headers.get("content-type", "application/json")})


class Env:
    pass


@pytest.fixture
def env(monkeypatch, tmp_path):
    for k in ("DONGAI_DESKTOP", "DONGAI_LICENSE_ENFORCE", "DONGAI_LOCAL_TOKEN", "DONGAI_LICENSE_SERVER",
              "DONGAI_LICENSE_RENEW"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("DONGAI_DATA_DIR", str(tmp_path / "data"))
    priv, pub = crypto.generate_keypair()
    kid = crypto.key_id_for(pub)
    monkeypatch.setenv("DONGAI_LICENSE_DEV", "1")
    monkeypatch.setenv("DONGAI_LICENSE_PUBKEYS", json.dumps({kid: pub}))
    monkeypatch.setattr(license_client, "get_machine_components", lambda: list(MY_COMPS))

    e = Env()
    e.t = FakeTime()
    e.priv, e.pub, e.kid = priv, pub, kid
    e.repos = make_memory_repos()
    settings = Settings(db=DbSettings(store="memory"), jwt_secret="t" * 8 + "x9K2mQ7vLp4Zr1Wn6Yb3Hd5Gs8Jc0Fa",
                        signing_private_key=priv, signing_public_key=pub, signing_kid=kid,
                        expire_interval_seconds=0)
    asyncio.run(create_admin_in_repo(e.repos, "root", ADMIN_PW, "super"))
    with TestClient(create_server_app(settings, e.repos, clock=e.t.server)) as tc:
        e.tc = tc
        e.net = Net(tc)
        yield e
    license_client.set_client(None)


def admin(env, method, path, **kw):
    r = env.tc.post("/admin/api/auth/login", json={"username": "root", "password": ADMIN_PW})
    assert r.status_code == 200, r.text
    h = {"Authorization": "Bearer " + r.json()["token"]}
    return env.tc.request(method, "/admin/api" + path, headers=h, **kw)


def issue(env, mc=MY_COMPS, expires_in=30 * DAY):
    r = admin(env, "POST", "/licenses", json={
        "machine_code": format_machine_code(mc), "plan": "pro", "features": ["video"],
        "expires_at": int(env.t.srv) + expires_in, "email": "u@example.com"})
    assert r.status_code == 201, r.text
    lic = r.json()["license"]
    return lic["lid"], lic["code"]


def mk_client(env, store=None, **kw):
    kw.setdefault("components_provider", lambda: list(MY_COMPS))
    return LicenseClient(store=store or MemoryLicenseStore(), clock=env.t.wall, mono=env.t.mono,
                         transport=httpx.MockTransport(env.net.handler),
                         server_url_provider=lambda: BASE, **kw)


@pytest.fixture
def activated(env):
    lid, code = issue(env)
    c = mk_client(env)
    assert c.activate(code)["state"] == "valid"
    env.lid, env.code, env.client = lid, code, c
    return c


def lease_payload(client):
    rec = client.store.read_lease()
    return license_token.verify_lease(rec["lease"], {client_kid(): client_pub()}, MY_COMPS, now=0)


def client_pub():
    return json.loads(__import__("os").environ["DONGAI_LICENSE_PUBKEYS"]).popitem()[1]


def client_kid():
    return json.loads(__import__("os").environ["DONGAI_LICENSE_PUBKEYS"]).popitem()[0]


def guard_app(client):
    license_client.set_client(client)
    app = FastAPI()

    @app.get("/api/data")
    async def read():
        return {"ok": True}

    @app.post("/api/data")
    async def write():
        return {"ok": True}

    app.add_middleware(LicenseGuardMiddleware)
    return TestClient(app)


# ---------------------------------------------------------------- 激活

def test_online_activation_success(env):
    lid, code = issue(env)
    c = mk_client(env)
    s = c.activate(code)
    assert s["state"] == "valid" and s["plan"] == "pro" and s["features"] == ["video"]
    assert s["readonly"] is False and s["needs_online"] is False and s["grace_until"] is None
    assert s["last_renew_ok_at"] == int(env.t.srv)
    assert s["lease_expires_at"] == int(env.t.srv) + DAY
    assert c.store.read() == code
    rec = c.store.read_lease()
    assert rec["server_time"] == int(env.t.srv) and rec["block"] is None
    assert env.net.calls == ["/license/v1/activate"]


def test_first_activation_requires_network(env):
    lid, code = issue(env)
    c = mk_client(env)
    env.net.down = True
    with pytest.raises(LicenseServerUnreachable):
        c.activate(code)
    assert c.store.read() is None and c.status()["state"] == "unactivated"
    env.net.down = False
    assert c.activate(code)["state"] == "valid"


def test_server_5xx_and_garbage_are_unreachable(env):
    lid, code = issue(env)
    c = mk_client(env)
    for forced in ((500, {"x": 1}), (502, {}), (200, {"nope": 1}), (404, {"code": "WHATEVER"}), (422, {"code": "VALIDATION_ERROR"})):
        env.net.force = forced
        with pytest.raises(LicenseServerUnreachable):
            c.activate(code)
        assert c.status()["state"] == "unactivated"


def test_offline_check_failure_does_not_hit_server(env):
    lid, code = issue(env, mc=["1111111111111111", "2222222222222222", "3333333333333333"])
    c = mk_client(env)
    with pytest.raises(license_token.MachineMismatch):
        c.activate(code)
    with pytest.raises(license_token.LicenseInvalid):
        c.activate("not a code")
    assert env.net.calls == []


def test_activation_server_errors_do_not_change_local_state(env):
    lid, code = issue(env)
    mk_client(env).activate(code)
    assert admin(env, "POST", f"/licenses/{lid}/suspend").status_code == 200
    c = mk_client(env)
    with pytest.raises(LicenseServerError) as ei:
        c.activate(code)
    assert ei.value.code == "LICENSE_SUSPENDED"
    assert c.store.read() is None and c.status()["state"] == "unactivated"


def test_server_time_corrects_wrong_local_clock(env):
    env.t.jump_wall(+2 * DAY)  # 本机时间快了 2 天：不能因此把还有 24 小时的租约判为过期
    lid, code = issue(env)
    c = mk_client(env)
    s = c.activate(code)
    assert s["state"] == "valid"
    env.t.advance(23 * HOUR)
    assert c.status()["state"] == "valid"
    env.t.advance(2 * HOUR)
    s = c.status()
    assert s["state"] == "grace" and s["grace_until"] == s["lease_expires_at"] + GRACE_SECONDS


# ---------------------------------------------------------------- 续租

def test_renew_updates_lease_and_time_base(env, activated):
    c = activated
    sid = lease_payload(c)["sid"]
    first_exp = c.status()["lease_expires_at"]
    env.t.advance(7 * HOUR)
    s = c.renew()
    assert s["state"] == "valid"
    assert s["last_renew_ok_at"] == int(env.t.srv)
    assert s["lease_expires_at"] == int(env.t.srv) + DAY > first_exp
    assert lease_payload(c)["sid"] == sid  # 续租不换会话
    assert env.net.calls[-1] == "/license/v1/renew"


def test_lease_expiry_enters_grace_then_lease_expired(env, activated):
    c = activated
    exp = c.status()["lease_expires_at"]
    env.t.advance(DAY - 1)
    assert c.status()["state"] == "valid"
    env.t.advance(2)
    s = c.status()
    assert s["state"] == "grace" and s["grace_until"] == exp + GRACE_SECONDS
    assert s["needs_online"] is True and s["readonly"] is False
    env.t.advance(GRACE_SECONDS - 3)
    assert c.status()["state"] == "grace"
    env.t.advance(2)
    s = c.status()
    assert s["state"] == "lease_expired" and s["readonly"] is True and s["needs_online"] is True


def test_renew_in_grace_succeeds(env, activated):
    c = activated
    env.t.advance(DAY + 5 * HOUR)
    assert c.status()["state"] == "grace"
    assert c.renew()["state"] == "valid"


def test_renew_beyond_grace_is_lease_expired_and_sticks(env, activated):
    c = activated
    env.t.advance(DAY + GRACE_SECONDS + 10)
    with pytest.raises(LicenseServerError) as ei:
        c.renew()
    assert ei.value.code == "LEASE_EXPIRED"
    s = c.status()
    assert s["state"] == "lease_expired" and s["readonly"] is True
    # 重新激活后恢复
    assert c.activate(env.code)["state"] == "valid"


def test_suspend_readonly_then_resume(env, activated):
    c = activated
    http = guard_app(c)
    import os
    os.environ["DONGAI_LICENSE_ENFORCE"] = "1"
    try:
        assert http.post("/api/data").status_code == 200
        admin(env, "POST", f"/licenses/{env.lid}/suspend")
        # 租约还没到期，但服务端已停用：下一次续租才知道
        assert c.status()["state"] == "valid"
        env.t.advance(6 * HOUR)
        with pytest.raises(LicenseServerError) as ei:
            c.renew()
        assert ei.value.code == "LICENSE_SUSPENDED"
        s = c.status()
        assert s["state"] == "suspended" and s["readonly"] is True
        assert http.get("/api/data").status_code == 200  # 只读：查看放行
        r = http.post("/api/data")
        assert r.status_code == 403 and r.json()["code"] == "LICENSE_READONLY" and r.json()["state"] == "suspended"
        assert http.put("/api/data").status_code == 403 and http.delete("/api/data").status_code == 403
        # 恢复后续租成功
        admin(env, "POST", f"/licenses/{env.lid}/resume")
        assert c.renew()["state"] == "valid"
        assert http.post("/api/data").status_code == 200
    finally:
        os.environ.pop("DONGAI_LICENSE_ENFORCE", None)


def test_state_persists_across_restart(env, tmp_path):
    lid, code = issue(env)
    store = FileLicenseStore(tmp_path / "lic" / "license.json")
    c = mk_client(env, store=store)
    c.activate(code)
    admin(env, "POST", f"/licenses/{lid}/suspend")
    env.t.advance(HOUR)
    with pytest.raises(LicenseServerError):
        c.renew()
    c2 = mk_client(env, store=FileLicenseStore(tmp_path / "lic" / "license.json"))
    assert c2.status()["state"] == "suspended"
    # 即使租约本身还有效，也不会因重启被放行
    assert lease_payload(c2)["exp"] > env.t.srv


def test_revoked_clears_local_authorization(env, activated):
    c = activated
    admin(env, "POST", f"/licenses/{env.lid}/revoke")
    env.t.advance(HOUR)
    with pytest.raises(LicenseServerError) as ei:
        c.renew()
    assert ei.value.code == "LICENSE_REVOKED"
    assert c.store.read() is None
    s = c.status()
    assert s["state"] == "revoked" and s["readonly"] is False
    with pytest.raises(NotActivated):
        c.renew()
    c.deactivate()
    assert c.status()["state"] == "unactivated"


def test_session_conflict_when_other_device_activates(env, activated):
    c = activated
    other = mk_client(env)  # 另一台设备（独立存储；同一授权码）
    assert other.activate(env.code)["state"] == "valid"
    env.t.advance(6 * HOUR)
    with pytest.raises(LicenseServerError) as ei:
        c.renew()
    assert ei.value.code == "LICENSE_SESSION_CONFLICT"
    s = c.status()
    assert s["state"] == "session_conflict" and s["readonly"] is False
    http = guard_app(c)
    import os
    os.environ["DONGAI_LICENSE_ENFORCE"] = "1"
    try:
        assert http.get("/api/data").status_code == 403  # 完全拦截，不是只读
        assert http.get("/api/data").json()["code"] == "LICENSE_REQUIRED"
    finally:
        os.environ.pop("DONGAI_LICENSE_ENFORCE", None)
    # 用授权码重新激活 -> 顶掉对方
    assert c.activate(env.code)["state"] == "valid"
    with pytest.raises(LicenseServerError) as ei:
        other.renew()
    assert ei.value.code == "LICENSE_SESSION_CONFLICT"


def test_expired_license_is_readonly_and_recovers_after_extend(env):
    lid, code = issue(env, expires_in=30 * HOUR)
    c = mk_client(env)
    c.activate(code)
    env.t.advance(25 * HOUR)  # 租约过期（宽限内），授权未过期
    assert c.status()["state"] == "grace"
    assert c.renew()["state"] == "valid"  # 新租约被授权到期时间截断（约 5 小时）
    assert c.status()["lease_expires_at"] == int(env.t.srv) + 5 * HOUR
    env.t.advance(6 * HOUR)  # 授权自身到期：宽限不适用
    s = c.status()
    assert s["state"] == "expired" and s["readonly"] is True
    with pytest.raises(LicenseServerError) as ei:
        c.renew()
    assert ei.value.code == "LICENSE_EXPIRED"
    assert c.status()["state"] == "expired"
    r = admin(env, "POST", f"/licenses/{lid}/extend", json={"expires_at": int(env.t.srv) + 30 * DAY})
    assert r.status_code == 200, r.text
    assert c.renew()["state"] == "valid"


def test_renew_license_invalid_clears(env, activated):
    c = activated
    priv2, pub2 = crypto.generate_keypair()
    kid2 = crypto.key_id_for(pub2)
    c._keys = lambda: {env.kid: env.pub, kid2: pub2}  # 本机信任两把钥匙，服务端只认第一把
    rec = c.store.read_lease()
    rec["lease"] = license_token.issue_lease(priv2, kid2, lid=env.lid, mc=MY_COMPS, sid="sid", ttl_seconds=DAY,
                                             iat=int(env.t.srv), lexp=int(env.t.srv) + DAY, plan="pro",
                                             features=["video"], cv=1)
    c.store.write_lease(rec)
    with pytest.raises(LicenseServerError) as ei:
        c.renew()
    assert ei.value.code == "LICENSE_INVALID"
    assert c.store.read() is None and c.status()["state"] == "invalid"


def test_machine_mismatch_from_server_is_persisted(env, activated):
    c = activated
    env.net.force = (403, {"code": "LICENSE_MACHINE_MISMATCH", "message": "x"})
    with pytest.raises(LicenseServerError):
        c.renew()
    env.net.force = None
    assert c.status()["state"] == "machine_mismatch"
    # 不再自动重试
    r = LicenseRenewer(c, monotonic=env.t.mono)
    n = len(env.net.calls)
    assert r.run_once() == "idle" and len(env.net.calls) == n


def test_rate_limited_does_not_change_state(env, activated):
    c = activated
    env.net.force = (429, {"code": "RATE_LIMITED", "message": "x"})
    with pytest.raises(LicenseServerError) as ei:
        c.renew()
    assert ei.value.code == "RATE_LIMITED"
    assert c.status()["state"] == "valid" and c.store.read_lease()["block"] is None


def test_forged_server_response_is_rejected(env, activated):
    """服务端（或中间人）返回的租约签名不对：按服务端异常处理，不改本地状态。"""
    c = activated
    priv2, pub2 = crypto.generate_keypair()
    fake = license_token.issue_lease(priv2, env.kid, lid=env.lid, mc=MY_COMPS, sid=lease_payload(c)["sid"],
                                     ttl_seconds=10 * DAY, iat=int(env.t.srv),
                                     lexp=int(env.t.srv) + 10 * DAY, plan="enterprise",
                                     features=["video", "admin"], cv=1)
    env.net.force = (200, {"lease": fake, "expires_at": 1, "server_time": int(env.t.srv),
                           "license": {"plan": "pro", "features": [], "expires_at": 1, "status": "active"}})
    before = c.store.read_lease()["lease"]
    with pytest.raises(LicenseServerUnreachable):
        c.renew()
    assert c.store.read_lease()["lease"] == before


# ---------------------------------------------------------------- H1：授权到期/套餐/功能点取自租约签名字段

def _forge_view(j):
    j["license"] = {"plan": "enterprise", "features": ["video", "admin", "export"],
                    "expires_at": int(j["server_time"]) + 3650 * DAY, "status": "active"}
    j["expires_at"] = int(j["server_time"]) + 3650 * DAY


def test_forged_response_json_cannot_change_entitlement(env):
    """响应 JSON 的 license.* 被改大（租约是真的）：状态与功能点仍以租约内签名值为准，记录里也不存这份副本。"""
    lid, code = issue(env, expires_in=2 * DAY)
    real_exp = int(env.t.srv) + 2 * DAY
    c = mk_client(env)
    env.net.mutate = _forge_view
    s = c.activate(code)
    assert s["state"] == "valid" and s["plan"] == "pro" and s["features"] == ["video"]
    assert s["expires_at"] == real_exp
    assert "license" not in c.store.read_lease()
    env.t.advance(DAY)
    s = c.renew()
    assert s["plan"] == "pro" and s["features"] == ["video"] and s["expires_at"] == real_exp
    # 授权真到期：响应再怎么改也是 expired（租约 lexp 已过）
    env.t.advance(DAY + 1)
    s = c.status()
    assert s["state"] == "expired" and s["readonly"] is True and s["expires_at"] == real_exp
    assert s["plan"] == "pro" and s["features"] == ["video"]


def test_tampered_lease_lexp_fails_signature(env, activated):
    c = activated
    rec = c.store.read_lease()
    data_b32, sig = rec["lease"].split(".")
    import base64
    raw = base64.b32decode(data_b32 + "=" * (-len(data_b32) % 8))
    obj = json.loads(raw)
    obj["lexp"] += 3650 * DAY
    obj["features"] = obj["features"] + ["admin"]
    new = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    rec["lease"] = base64.b32encode(new).decode().rstrip("=") + "." + sig
    c.store.write_lease(rec)
    assert c.status()["state"] == "invalid"
    with pytest.raises(NotActivated):
        c.renew()


def test_tampered_lease_in_response_is_rejected(env, activated):
    """中间人改写响应里的租约 lexp：验签失败，按服务端异常处理，本地记录不变。"""
    import base64
    c = activated
    env.t.advance(HOUR)

    def swap(j):
        d, sg = j["lease"].split(".")
        o = json.loads(base64.b32decode(d + "=" * (-len(d) % 8)))
        o["lexp"] += DAY
        j["lease"] = base64.b32encode(json.dumps(o, sort_keys=True, separators=(",", ":")).encode()).decode().rstrip("=") + "." + sg
    env.net.mutate = swap
    before = c.store.read_lease()["lease"]
    with pytest.raises(LicenseServerUnreachable):
        c.renew()
    assert c.store.read_lease()["lease"] == before


def test_extend_then_renew_updates_expiry_and_records_cv(env):
    lid, code = issue(env, expires_in=2 * DAY)
    c = mk_client(env)
    c.activate(code)
    first = c.status()["expires_at"]
    assert first == int(env.t.srv) + 2 * DAY and c.store.read_lease()["cv"] == 1
    new_exp = int(env.t.srv) + 60 * DAY
    assert admin(env, "POST", f"/licenses/{lid}/extend", json={"expires_at": new_exp}).status_code == 200
    assert c.status()["expires_at"] == first  # 续租前客户端不知道
    env.t.advance(HOUR)
    s = c.renew()
    assert s["state"] == "valid" and s["expires_at"] == new_exp
    assert c.store.read_lease()["cv"] == 2
    assert lease_payload(c)["lexp"] == new_exp
    # 本机仍存着旧授权码（exp 较早）：以租约为准，不会因旧码的 exp 判到期
    env.t.advance(3 * DAY)
    assert c.store.read() == code
    assert c.renew()["state"] == "valid"


def test_extend_recovers_from_expired(env):
    lid, code = issue(env, expires_in=30 * HOUR)
    c = mk_client(env)
    c.activate(code)
    env.t.advance(31 * HOUR)
    assert c.status()["state"] == "expired"
    admin(env, "POST", f"/licenses/{lid}/extend", json={"expires_at": int(env.t.srv) + 30 * DAY})
    s = c.renew()
    assert s["state"] == "valid" and s["expires_at"] == int(env.t.srv) + 30 * DAY


def test_plan_downgrade_then_renew_reduces_features(env):
    lid, code = issue(env)
    c = mk_client(env)
    s = c.activate(code)
    assert s["plan"] == "pro" and s["features"] == ["video"]
    asyncio.run(env.repos.licenses.update(lid, {"plan": "basic", "features": []}))
    assert c.status()["features"] == ["video"]  # 续租前仍是旧值
    env.t.advance(HOUR)
    s = c.renew()
    assert s["plan"] == "basic" and s["features"] == [] and s["state"] == "valid"
    assert lease_payload(c)["features"] == []
    # 升级同理
    asyncio.run(env.repos.licenses.update(lid, {"plan": "enterprise", "features": ["video", "export"]}))
    env.t.advance(HOUR)
    s = c.renew()
    assert s["plan"] == "enterprise" and s["features"] == ["video", "export"]


def test_old_v1_lease_in_store_is_not_trusted(env, activated):
    c = activated
    rec = c.store.read_lease()
    old = {"typ": "lease", "v": 1, "kid": env.kid, "lid": env.lid, "mc": MY_COMPS, "sid": "s",
           "iat": int(env.t.srv), "exp": int(env.t.srv) + DAY, "st": "active"}
    data = license_token._canonical(old)
    rec["lease"] = license_token._b32e(data) + "." + license_token._b32e(crypto.sign(env.priv, data))
    c.store.write_lease(rec)
    assert c.status()["state"] == "invalid"


# ---------------------------------------------------------------- 时钟回拨

def test_clock_rollback_requires_online_renew(env, activated):
    c = activated
    http = guard_app(c)
    import os
    os.environ["DONGAI_LICENSE_ENFORCE"] = "1"
    try:
        env.t.advance(HOUR)
        env.t.jump_wall(-240)  # 回拨 4 分钟：在容差内
        assert c.status()["state"] == "valid"
        env.t.jump_wall(-2 * HOUR)  # 回拨 2 小时
        s = c.status()
        assert s["state"] == "clock_rollback" and s["needs_online"] is True
        assert http.get("/api/data").status_code == 403  # 完全拦截
        env.net.down = True
        assert c.status()["state"] == "clock_rollback"  # 断网不能自行恢复
        env.net.down = False
        assert c.renew()["state"] == "valid"  # 联网续租成功，以 server_time 修正时间基准
        assert http.post("/api/data").status_code == 200
    finally:
        os.environ.pop("DONGAI_LICENSE_ENFORCE", None)


def test_clock_rollback_detected_after_restart_via_wall_max(env, tmp_path):
    lid, code = issue(env)
    f = tmp_path / "lic" / "license.json"
    c = mk_client(env, store=FileLicenseStore(f))
    c.activate(code)
    env.t.advance(3 * HOUR)
    c.touch()  # 续租线程每个周期做的事：记录见过的最大墙钟
    env.t.jump_wall(-2 * HOUR)
    c2 = mk_client(env, store=FileLicenseStore(f))  # 模拟进程重启：单调时钟不可比，靠落盘的墙钟判断
    assert c2.status()["state"] == "clock_rollback"
    assert c2.renew()["state"] == "valid"


def test_monotonic_clock_catches_wall_freeze_in_process(env, activated):
    """同一进程内：墙钟没动但单调时钟走了 10 分钟 = 墙钟被拨回/冻结。"""
    c = activated
    env.t.m += 600
    assert c.status()["state"] == "clock_rollback"
    assert c.renew()["state"] == "valid"


def test_rollback_cannot_extend_grace(env, activated):
    c = activated
    env.t.advance(DAY + GRACE_SECONDS + HOUR)
    assert c.status()["state"] == "lease_expired"
    env.t.jump_wall(-(GRACE_SECONDS))  # 把系统时间拨回宽限内
    assert c.status()["state"] in ("clock_rollback", "lease_expired")
    assert c.status()["readonly"] is False or c.status()["state"] == "clock_rollback"


# ---------------------------------------------------------------- 存储兼容

def test_old_format_store_requires_reactivation(env, tmp_path):
    lid, code = issue(env)
    f = tmp_path / "old" / "license.json"
    f.parent.mkdir(parents=True)
    f.write_text(json.dumps({"code": code, "saved_at": 1}))  # L-26 的文件：只有授权码
    c = mk_client(env, store=FileLicenseStore(f))
    s = c.status()
    assert s["state"] == "unactivated" and s["needs_online"] is True
    with pytest.raises(NotActivated):
        c.renew()
    http = guard_app(c)
    import os
    os.environ["DONGAI_LICENSE_ENFORCE"] = "1"
    try:
        assert http.get("/api/data").status_code == 403
    finally:
        os.environ.pop("DONGAI_LICENSE_ENFORCE", None)
    assert c.activate(code)["state"] == "valid"
    assert mk_client(env, store=FileLicenseStore(f)).status()["state"] == "valid"


def test_tampered_store_fails_closed(env, activated):
    c = activated
    rec = c.store.read_lease()
    rec["lease"] = rec["lease"][:-3] + "AAA"
    c.store.write_lease(rec)
    assert c.status()["state"] == "invalid"
    rec["server_time"] = "bad"
    c.store.write_lease(rec)
    assert c.status()["state"] == "unactivated"  # 记录不完整 = 需要联网重新激活，不放行


# ---------------------------------------------------------------- 续租线程

def mk_renewer(env, client, **kw):
    kw.setdefault("monotonic", env.t.mono)
    kw.setdefault("jitter", lambda a, b: a)
    return LicenseRenewer(client, **kw)


def test_renewer_schedule_and_early_threshold(env, activated):
    r = mk_renewer(env, activated)
    assert r.run_once() == "wait"            # 刚激活，不需要续租
    env.t.advance(6 * HOUR - 1)
    assert r.run_once() == "wait"
    env.t.advance(2)
    assert r.run_once() == "renewed"         # 到 6 小时
    assert activated.status()["last_renew_ok_at"] == int(env.t.srv)
    # 间隔很长时，租约剩余不足 12 小时也要立即续租
    r2 = mk_renewer(env, activated, interval=10 * DAY)
    assert r2.run_once() == "wait"
    env.t.advance(13 * HOUR)
    assert r2.run_once() == "renewed"


def test_renewer_renews_immediately_when_expired_or_grace(env, activated):
    env.t.advance(DAY + HOUR)
    assert activated.status()["state"] == "grace"
    assert mk_renewer(env, activated).run_once() == "renewed"
    assert activated.status()["state"] == "valid"


def test_renewer_backoff_does_not_change_state(env, activated):
    c = activated
    r = mk_renewer(env, c)
    env.t.advance(7 * HOUR)
    env.net.down = True
    assert r.run_once() == "unreachable"
    assert c.status()["state"] == "valid" and c.store.read_lease()["block"] is None
    n = len(env.net.calls)
    assert r.run_once() == "backoff" and len(env.net.calls) == n  # 退避期内不请求
    env.t.advance(299)
    assert r.run_once() == "backoff"
    env.t.advance(2)
    assert r.run_once() == "unreachable"      # 过了 300 秒再试
    env.net.down = False
    env.t.advance(301)
    assert r.run_once() == "renewed"
    # 5xx 与 429 同样只退避
    env.t.advance(7 * HOUR)
    env.net.force = (503, {})
    assert r.run_once() == "unreachable"
    env.t.advance(301)
    env.net.force = (429, {"code": "RATE_LIMITED", "message": ""})
    assert r.run_once() == "rate_limited"
    env.t.advance(59)
    assert r.run_once() == "backoff"
    env.t.advance(2)
    env.net.force = None
    assert r.run_once() == "renewed"


def test_renewer_backoff_jitter_range(env, activated):
    seen = []
    r = LicenseRenewer(activated, monotonic=env.t.mono, jitter=lambda a, b: (seen.append((a, b)), a)[1])
    env.t.advance(7 * HOUR)
    env.net.down = True
    r.run_once()
    assert seen == [(300, 600)]


def test_renewer_suspended_hourly_retry_and_recovery(env, activated):
    c = activated
    r = mk_renewer(env, c)
    admin(env, "POST", f"/licenses/{env.lid}/suspend")
    env.t.advance(7 * HOUR)
    assert r.run_once() == "rejected:LICENSE_SUSPENDED"
    assert c.status()["state"] == "suspended"
    n = len(env.net.calls)
    env.t.advance(3000)
    assert r.run_once() == "wait" and len(env.net.calls) == n
    env.t.advance(601)
    assert r.run_once() == "rejected:LICENSE_SUSPENDED"  # 每小时一次
    admin(env, "POST", f"/licenses/{env.lid}/resume")
    env.t.advance(HOUR + 1)
    assert r.run_once() == "renewed"
    assert c.status()["state"] == "valid"


def test_renewer_stops_retrying_on_terminal_states(env, activated):
    c = activated
    r = mk_renewer(env, c)
    other = mk_client(env)
    other.activate(env.code)
    env.t.advance(7 * HOUR)
    assert r.run_once() == "rejected:LICENSE_SESSION_CONFLICT"
    n = len(env.net.calls)
    env.t.advance(10 * DAY)
    assert r.run_once() == "idle" and len(env.net.calls) == n


def test_renewer_lease_expired_by_server_is_terminal(env, activated):
    r = mk_renewer(env, activated)
    env.t.advance(DAY + GRACE_SECONDS + 10)
    assert activated.status()["state"] == "lease_expired"
    assert r.run_once() == "rejected:LEASE_EXPIRED"
    assert r.run_once() == "idle"


def test_renewer_clock_rollback_triggers_immediate_renew(env, activated):
    r = mk_renewer(env, activated)
    env.t.advance(HOUR)
    env.t.jump_wall(-2 * HOUR)
    assert activated.status()["state"] == "clock_rollback"
    assert r.run_once() == "renewed"
    assert activated.status()["state"] == "valid"


def test_renewer_thread_survives_failures(env, activated, caplog):
    caplog.set_level(logging.DEBUG)
    c = activated
    env.t.advance(7 * HOUR)
    env.net.down = True
    r = LicenseRenewer(c, tick=0.005, backoff_range=(0.005, 0.01), monotonic=time.monotonic)
    r.start()
    try:
        deadline = time.time() + 5
        while len(env.net.calls) < 4 and time.time() < deadline:
            time.sleep(0.01)
        assert len(env.net.calls) >= 4 and r.is_running()  # 失败后仍在重试

        # 客户端内部抛任意异常：线程照样活着
        boom = threading.Event()
        orig = c.status

        def bad():
            boom.set()
            raise RuntimeError("boom " + env.code)
        c.status = bad
        assert boom.wait(5)
        time.sleep(0.05)
        assert r.is_running()
        c.status = orig
    finally:
        r.stop()
    assert not r.is_running()
    assert env.code not in caplog.text


def test_renewer_start_stop_idempotent_and_enable_rules(env, monkeypatch):
    assert license_config.renewer_enabled() is False
    monkeypatch.setenv("DONGAI_LICENSE_RENEW", "1")
    assert license_config.renewer_enabled() is True
    monkeypatch.delenv("DONGAI_LICENSE_RENEW")
    monkeypatch.setenv("DONGAI_DESKTOP", "1")
    assert license_config.renewer_enabled() is True
    r = LicenseRenewer(mk_client(env), tick=0.01)
    r.start(); r.start()
    assert r.is_running()
    r.stop(); r.stop()
    assert not r.is_running()


# ---------------------------------------------------------------- 配置安全

def test_server_url_override_rules(monkeypatch):
    monkeypatch.delenv("DONGAI_DESKTOP", raising=False)
    monkeypatch.delenv("DONGAI_LICENSE_DEV", raising=False)
    monkeypatch.setenv("DONGAI_LICENSE_SERVER", "http://127.0.0.1:18100/")
    assert license_config.get_server_url() == license_config.DEFAULT_SERVER_URL  # 没开 DEV：忽略
    monkeypatch.setenv("DONGAI_LICENSE_DEV", "1")
    assert license_config.get_server_url() == "http://127.0.0.1:18100"
    monkeypatch.setenv("DONGAI_LICENSE_SERVER", "ftp://x")
    assert license_config.get_server_url() == license_config.DEFAULT_SERVER_URL
    monkeypatch.setenv("DONGAI_LICENSE_SERVER", "http://127.0.0.1:18100")
    monkeypatch.setenv("DONGAI_DESKTOP", "1")  # 桌面模式一律忽略
    assert license_config.get_server_url() == license_config.DEFAULT_SERVER_URL


def test_desktop_mode_ignores_server_and_pubkey_env(env, monkeypatch):
    monkeypatch.setenv("DONGAI_DESKTOP", "1")
    monkeypatch.setenv("DONGAI_LICENSE_SERVER", "https://evil.example.org")
    assert license_config.get_server_url() == license_config.DEFAULT_SERVER_URL
    assert license_client.get_public_keys() == license_client.license_keys.PUBLIC_KEYS
    # 用环境变量里的钥匙签的授权码，桌面模式下离线校验就失败，根本不会联网
    lid, code = issue(env)
    c = LicenseClient(store=MemoryLicenseStore(), components_provider=lambda: list(MY_COMPS),
                      transport=httpx.MockTransport(env.net.handler))
    with pytest.raises(license_token.LicenseInvalid):
        c.activate(code)
    assert env.net.calls == []


def test_grace_not_configurable_by_env(monkeypatch):
    monkeypatch.setenv("DONGAI_LICENSE_GRACE", "999999999")
    monkeypatch.setenv("DONGAI_LICENSE_GRACE_SECONDS", "999999999")
    assert license_client.GRACE_SECONDS == 259200


def test_tls_verification_is_not_disabled(env, monkeypatch):
    seen = {}
    orig = httpx.Client

    def spy(*a, **kw):
        seen.update(kw)
        return orig(*a, **kw)
    monkeypatch.setattr(license_client.httpx, "Client", spy)
    lid, code = issue(env)
    mk_client(env).activate(code)
    assert seen.get("verify", True) is True and seen["timeout"] == 10


# ---------------------------------------------------------------- 日志

def test_logs_never_contain_code_or_lease(env, caplog):
    caplog.set_level(logging.DEBUG)
    lid, code = issue(env)
    c = mk_client(env)
    c.activate(code)
    lease = c.store.read_lease()["lease"]
    env.t.advance(7 * HOUR)
    env.net.down = True
    r = mk_renewer(env, c)
    r.run_once()
    env.net.down = False
    env.t.advance(301)
    r.run_once()
    admin(env, "POST", f"/licenses/{lid}/suspend")
    env.t.advance(7 * HOUR)
    r.run_once()
    env.net.force = (500, {"echo": code})
    env.t.advance(2 * HOUR)
    r.run_once()
    env.net.force = None
    lease2 = c.store.read_lease()["lease"]
    text = caplog.text
    assert code not in text and lease not in text and lease2 not in text
    assert license_token.format_for_display(code).replace("\n", "")[:20] not in text.replace("\n", "")
    assert text  # 确实有日志可查


# ---------------------------------------------------------------- /api/license 接口

@pytest.fixture
def api(env):
    from api import license as license_api
    app = FastAPI()
    app.include_router(license_api.router)
    license_api._renew_limiter = license_api._SlidingLimiter(3, 60.0, clock=env.t.mono)
    return TestClient(app)


def test_api_activate_status_and_new_fields(env, api):
    lid, code = issue(env)
    license_client.set_client(mk_client(env))
    r = api.post("/api/license/activate", json={"code": code})
    assert r.status_code == 200 and r.json()["state"] == "valid"
    s = api.get("/api/license/status").json()
    for k in ("grace_until", "lease_expires_at", "readonly", "last_renew_ok_at", "needs_online"):
        assert k in s
    assert s["readonly"] is False and s["lease_expires_at"] == int(env.t.srv) + DAY
    assert "server_blocked" not in s
    env.t.advance(DAY + HOUR)
    s = api.get("/api/license/status").json()
    assert s["state"] == "grace" and s["grace_until"] == s["lease_expires_at"] + GRACE_SECONDS and s["needs_online"]


def test_api_activate_network_down_and_errors(env, api):
    lid, code = issue(env)
    license_client.set_client(mk_client(env))
    env.net.down = True
    r = api.post("/api/license/activate", json={"code": code})
    assert r.status_code == 503 and r.json()["code"] == "LICENSE_SERVER_UNREACHABLE" and "网络" in r.json()["message"]
    env.net.down = False
    for status, code_, http_status in (
            (403, "LICENSE_SUSPENDED", 403), (403, "LICENSE_REVOKED", 403), (409, "LICENSE_SESSION_CONFLICT", 409),
            (401, "LEASE_EXPIRED", 403), (401, "LICENSE_INVALID", 400), (403, "LICENSE_EXPIRED", 403),
            (403, "LICENSE_MACHINE_MISMATCH", 403), (429, "RATE_LIMITED", 429)):
        env.net.force = (status, {"code": code_, "message": "server"})
        r = api.post("/api/license/activate", json={"code": code})
        assert r.status_code == http_status and r.json()["code"] == code_ and r.json()["message"], code_
    env.net.force = (500, {})
    assert api.post("/api/license/activate", json={"code": code}).json()["code"] == "LICENSE_SERVER_UNREACHABLE"
    # 离线校验失败不打服务端
    env.net.calls.clear()
    assert api.post("/api/license/activate", json={"code": "garbage"}).status_code == 400
    assert env.net.calls == []


def test_api_renew_now_and_rate_limit(env, api):
    lid, code = issue(env)
    license_client.set_client(mk_client(env))
    assert api.post("/api/license/renew-now").status_code == 409  # 未激活
    api.post("/api/license/activate", json={"code": code})
    env.t.advance(HOUR)
    r = api.post("/api/license/renew-now")
    assert r.status_code == 200 and r.json()["last_renew_ok_at"] == int(env.t.srv)
    assert api.post("/api/license/renew-now").status_code == 200
    assert api.post("/api/license/renew-now").status_code == 200
    r = api.post("/api/license/renew-now")  # 第 4 次（本分钟内，其中一次是未激活的 409 也计数）
    assert r.status_code == 429 and r.json()["code"] == "RATE_LIMITED"
    env.t.advance(61)
    env.net.down = True
    r = api.post("/api/license/renew-now")
    assert r.status_code == 503 and r.json()["code"] == "LICENSE_SERVER_UNREACHABLE"
    env.net.down = False
    admin(env, "POST", f"/licenses/{lid}/suspend")
    env.t.advance(61)
    r = api.post("/api/license/renew-now")
    assert r.status_code == 403 and r.json()["code"] == "LICENSE_SUSPENDED" and r.json()["state"] == "suspended"
    assert api.get("/api/license/status").json()["readonly"] is True
