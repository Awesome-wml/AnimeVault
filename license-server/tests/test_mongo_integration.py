"""Mongo 存储的集成验证（真实 mongod）。仅当 LS_MONGO_URL 存在且库名含 test 时运行。

每个用例开始前清空测试库的相关集合，千万别指向正式库。
"""
import asyncio
import dataclasses
import os
import time

import pytest
from fastapi.testclient import TestClient

from app.config import DbSettings
from app.create_admin import create_admin_in_repo
from app.errors import ApiError
from app.main import create_app
from app.repo.base import DuplicateError
from app.repo.mongo import make_mongo_repos
from app.services.audit import Actor, AuditService
from app.services.licenses import LicenseService
from tests.conftest import PW, Clock, comps, issue_body, login
from dongai_license.machine_code import format_machine_code

MONGO_URL = os.environ.get("LS_MONGO_URL")
MONGO_DB = os.environ.get("LS_MONGO_DB", "dongai_license")
pytestmark = pytest.mark.skipif(not (MONGO_URL and "test" in MONGO_DB.lower()),
                                reason="需要 LS_MONGO_URL 且库名含 test")

COLS = ("licenses", "admins", "audit_logs", "license_events", "keys", "devices", "leases", "activation_reqs")
MC = comps()


@pytest.fixture(autouse=True)
def clean_db():
    from pymongo import MongoClient
    c = MongoClient(MONGO_URL)
    for n in COLS:
        c[MONGO_DB][n].delete_many({})
    c.close()
    yield


@pytest.fixture
def msettings(settings):
    return dataclasses.replace(settings, db=DbSettings(store="mongo", mongo_url=MONGO_URL, mongo_db=MONGO_DB))


def raw_col(name):
    from pymongo import MongoClient
    c = MongoClient(MONGO_URL)
    return c, c[MONGO_DB][name]


def lic(lid, status="pending"):
    return {"lid": lid, "uid": None, "email": "x@y.com", "plan": "pro", "features": [], "dev_max": 1,
            "status": status, "issued_at": 1000, "expires_at": int(time.time()) + 86400 * 30, "activated_at": None, "note": None,
            "created_by": "a", "machine_components": list(MC), "code": "C" + lid, "code_version": 1,
            "last_seen_at": None, "active_sid": None, "last_seen_ip": None, "last_renew_at": None}


def run_with_repos(fn):
    async def go():
        r = make_mongo_repos(MONGO_URL, MONGO_DB)
        try:
            await r.ensure_ready()
            return await fn(r)
        finally:
            await r.close()
    return asyncio.run(go())


def test_concurrent_mark_activated_only_one_wins(msettings, clk):
    async def go(r):
        await r.licenses.insert(lic("lic_c1"))
        svc = LicenseService(r, msettings, AuditService(r.audit), clk)
        res = await asyncio.gather(*[svc.mark_activated("lic_c1", Actor(None, "ip")) for _ in range(8)],
                                   return_exceptions=True)
        ok = [x for x in res if isinstance(x, dict)]
        bad = [x for x in res if isinstance(x, ApiError)]
        assert len(ok) == 1 and len(bad) == 7 and all(b.status == 409 for b in bad), res
        evs = [e["type"] for e in await r.events.list_for("lic_c1")]
        assert evs.count("activated") == 1
        _, total = await r.audit.search(action="license.activate")
        assert total == 1
    run_with_repos(go)


def test_concurrent_conditional_update_atomic(msettings):
    async def go(r):
        await r.licenses.insert(lic("lic_c2", status="active"))
        res = await asyncio.gather(*[r.licenses.update("lic_c2", {"note": f"n{i}", "status": "suspended"},
                                                      expect_status=("active",)) for i in range(10)])
        assert sum(1 for x in res if x is not None) == 1
        # 状态已变，条件不满足
        assert await r.licenses.update("lic_c2", {"note": "z"}, expect_status=("active",)) is None
        assert (await r.licenses.get("lic_c2"))["status"] == "suspended"
        # 不存在的授权
        assert await r.licenses.update("nope", {"note": "z"}) is None
    run_with_repos(go)


def test_unique_indexes(msettings):
    async def go(r):
        await r.licenses.insert(lic("lic_u"))
        with pytest.raises(DuplicateError):
            await r.licenses.insert(lic("lic_u"))
        admin = {"id": "a1", "username": "bob", "password_hash": "x", "role": "ops", "enabled": True,
                 "created_at": 1}
        await r.admins.insert(admin)
        with pytest.raises(DuplicateError):
            await r.admins.insert({**admin, "id": "a2"})
        # 并发重复创建管理员只成功一个
        docs = [{**admin, "id": f"b{i}", "username": "carol"} for i in range(5)]
        res = await asyncio.gather(*[r.admins.insert(d) for d in docs], return_exceptions=True)
        assert sum(1 for x in res if isinstance(x, DuplicateError)) == 4
        # 同一授权同一会话只能有一条租约
        info = await r._db["leases"].index_information()
        assert any(v.get("unique") for v in info.values())
    run_with_repos(go)


def test_audit_is_append_only(msettings, clk):
    from app.repo.mongo import MongoAudit
    for repo_cls in (MongoAudit,):
        assert not any(hasattr(repo_cls, n) for n in ("update", "delete", "remove", "replace", "upsert"))

    async def go(r):
        svc = LicenseService(r, msettings, AuditService(r.audit), clk)
        await r.licenses.insert(lic("lic_a"))
        await svc.mark_activated("lic_a", Actor(None, "ip"))
        await svc.suspend(Actor(None, "ip"), "lic_a")
    run_with_repos(go)
    c, col = raw_col("audit_logs")
    before = list(col.find({}).sort("_id", 1))
    assert len(before) == 2
    run_with_repos(lambda r: _more_ops(r, msettings, clk))
    after = list(col.find({}).sort("_id", 1))
    c.close()
    assert len(after) == 4 and after[:2] == before  # 旧记录一字未动


async def _more_ops(r, msettings, clk):
    svc = LicenseService(r, msettings, AuditService(r.audit), clk)
    await svc.resume(Actor(None, "ip"), "lic_a")
    await svc.revoke(Actor(None, "ip"), "lic_a")
    await r.audit.search()


def _mk_client(msettings, clk):
    return TestClient(create_app(msettings, None, clock=clk))


def _issue(client, h, **kw):
    r = client.post("/admin/api/licenses", json=issue_body(machine_code=format_machine_code(MC), **kw), headers=h)
    assert r.status_code == 201, r.text
    return r.json()["license"]


def _activate(client, code):
    return client.post("/license/v1/activate", json={"license_code": code, "machine_components": MC,
                                                     "app_version": "1.0"})


def _renew(client, lease):
    return client.post("/license/v1/renew", json={"lease": lease, "machine_components": MC, "app_version": "1.0"})


def test_restart_keeps_data(msettings, clk):
    run_with_repos(lambda r: create_admin_in_repo(r, "root", PW, "super"))
    with _mk_client(msettings, clk) as c1:
        h = login(c1, "root")
        l = _issue(c1, h)
        lease = _activate(c1, l["code"]).json()["lease"]
    # 重启：新 app 指向同一库
    clk.advance(60)
    with _mk_client(msettings, clk) as c2:
        h2 = login(c2, "root")
        got = c2.get(f"/admin/api/licenses/{l['lid']}", headers=h2).json()
        assert got["status"] == "active"
        r = _renew(c2, lease)
        assert r.status_code == 200, r.text
        # 续租后可再用授权码重新激活（顶替会话），也能签发新授权
        assert _activate(c2, l["code"]).status_code == 200
        assert _renew(c2, lease).status_code == 409  # 旧会话被顶掉
        _issue(c2, h2, email="b@example.com")
    with _mk_client(msettings, clk) as c3:
        h3 = login(c3, "root")
        lst = c3.get("/admin/api/licenses", headers=h3).json()
        assert lst["total"] == 2


def test_full_http_flow(msettings, clk):
    run_with_repos(lambda r: create_admin_in_repo(r, "root", PW, "super"))
    with _mk_client(msettings, clk) as c:
        h = login(c, "root")
        l = _issue(c, h)
        lid = l["lid"]
        a = _activate(c, l["code"])
        assert a.status_code == 200, a.text
        lease = a.json()["lease"]
        assert _renew(c, lease).status_code == 200
        assert c.post(f"/admin/api/licenses/{lid}/suspend", headers=h).status_code == 200
        r = _renew(c, lease)
        assert r.status_code == 403 and r.json()["code"] == "LICENSE_SUSPENDED"
        assert c.post(f"/admin/api/licenses/{lid}/suspend", headers=h).status_code == 409
        assert c.post(f"/admin/api/licenses/{lid}/resume", headers=h).status_code == 200
        assert _renew(c, lease).status_code == 200
        assert c.post(f"/admin/api/licenses/{lid}/revoke", headers=h).status_code == 200
        r = _renew(c, lease)
        assert r.status_code == 403 and r.json()["code"] == "LICENSE_REVOKED"
        types = [e["type"] for e in c.get(f"/admin/api/licenses/{lid}/events?order=asc", headers=h).json()["items"]]
        assert types[:2] == ["issued", "activated"] and types[-1] == "revoked"
        assert "suspended" in types and "resumed" in types
        audit = c.get("/admin/api/audit", headers=h).json()
        assert audit["total"] >= 5


# ---------- L-45：设备/踢下线/申请单/extend（复用 test_l45_ops 的场景）----------
def _l45_headers(c):
    return {k: login(c, n) for k, n in (("root", "root"), ("ops", "oper"), ("ro", "viewer"))}


def _l45_client(msettings, clk):
    async def seed(r):
        for u, role in (("root", "super"), ("oper", "ops"), ("viewer", "readonly")):
            await create_admin_in_repo(r, u, PW, role)
    run_with_repos(seed)
    return _mk_client(msettings, clk)


def test_l45_devices_kick_unbind(msettings, clk):
    from tests.test_l45_ops import scenario_devices_kick_unbind, scenario_kick_revoked
    with _l45_client(msettings, clk) as c:
        scenario_devices_kick_unbind(c, _l45_headers(c))
        scenario_kick_revoked(c, _l45_headers(c))


def test_l45_requests(msettings, clk):
    from tests.test_l45_ops import scenario_request_rate_limit, scenario_requests
    with _l45_client(msettings, clk) as c:
        scenario_requests(c, _l45_headers(c))
    with _mk_client(msettings, clk) as c:
        c.app.state.ctx.requests.limiter._hits.clear()
        scenario_request_rate_limit(c, clk)


def test_l45_extend_expired(msettings, clk):
    from tests.test_l45_ops import scenario_extend_expired
    with _l45_client(msettings, clk) as c:
        scenario_extend_expired(c, _l45_headers(c))


def test_l45_pagination_and_username(msettings, clk):
    with _l45_client(msettings, clk) as c:
        h = _l45_headers(c)
        lid = _issue(c, h["ops"])["lid"]
        c.post(f"/admin/api/licenses/{lid}/suspend", headers=h["ops"])  # pending 不可停用：409 不写事件
        _activate(c, c.get(f"/admin/api/licenses/{lid}", headers=h["ops"]).json()["code"])
        c.post(f"/admin/api/licenses/{lid}/suspend", headers=h["ops"])
        c.post(f"/admin/api/licenses/{lid}/resume", headers=h["ops"])
        r = c.get(f"/admin/api/licenses/{lid}/events?page_size=2", headers=h["ops"]).json()
        assert r["total"] >= 5 and [e["type"] for e in r["items"]] == ["resumed", "suspended"]
        assert r["items"][0]["actor_username"] == "oper"
        r = c.get(f"/admin/api/licenses/{lid}/events?order=asc&page_size=1", headers=h["ops"]).json()
        assert r["items"][0]["type"] == "issued" and r["items"][0]["actor_username"] == "oper"
        assert c.get("/admin/api/licenses?page_size=1", headers=h["ops"]).json()["items"][0]["created_by_username"] == "oper"
        a = c.get("/admin/api/admins?page_size=2&page=2", headers=h["root"]).json()
        assert a["total"] == 3 and len(a["items"]) == 1
        au = c.get("/admin/api/audit?action=license.suspend", headers=h["root"]).json()
        assert au["items"][0]["admin_username"] == "oper"
        assert c.get("/admin/api/meta", headers=h["ro"]).json()["plans"]
