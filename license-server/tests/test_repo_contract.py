"""同一套仓库用例：内存实现始终跑；Mongo 实现仅当 LS_MONGO_URL 存在且库名含 test 才跑。"""
import asyncio
import os

import pytest

from app.repo.base import DuplicateError
from app.repo.memory import make_memory_repos

MONGO_URL = os.environ.get("LS_MONGO_URL")
MONGO_DB = os.environ.get("LS_MONGO_DB", "dongai_license")
mongo_ok = bool(MONGO_URL) and "test" in MONGO_DB.lower()


async def with_repos(kind, fn):
    if kind == "memory":
        return await fn(make_memory_repos())
    from app.repo.mongo import make_mongo_repos
    r = make_mongo_repos(MONGO_URL, MONGO_DB)
    try:
        for c in ("licenses", "admins", "audit_logs", "license_events", "keys", "devices", "leases"):
            await r._db[c].delete_many({})  # 仅测试库
        await r.ensure_ready()
        return await fn(r)
    finally:
        await r.close()


KINDS = ["memory", pytest.param("mongo", marks=pytest.mark.skipif(not mongo_ok, reason="需要 LS_MONGO_URL 且库名含 test"))]


def lic(lid, status="pending", comps=("a1", "b2", "c3"), email="x@y.com", issued=1000, exp=5000):
    return {"lid": lid, "uid": None, "email": email, "plan": "pro", "features": [], "dev_max": 1,
            "status": status, "issued_at": issued, "expires_at": exp, "activated_at": None, "note": None,
            "created_by": "a", "machine_components": list(comps), "code": "C" + lid, "code_version": 1,
            "last_seen_at": None, "active_sid": None, "last_seen_ip": None,
            "last_renew_at": None}


@pytest.mark.parametrize("kind", KINDS)
def test_licenses(kind):
    async def go(r):
        L = r.licenses
        await L.insert(lic("lic_1", issued=1))
        await L.insert(lic("lic_2", status="active", issued=2, email="Bob@Y.com", exp=10))
        await L.insert(lic("lic_3", status="revoked", issued=3, comps=("x", "y")))
        with pytest.raises(DuplicateError):
            await L.insert(lic("lic_1"))
        assert (await L.get("lic_1"))["code"] == "Clic_1" and await L.get("zz") is None
        assert "_id" not in await L.get("lic_1")
        items, total = await L.search(skip=0, limit=2)
        assert total == 3 and [i["lid"] for i in items] == ["lic_3", "lic_2"]
        assert (await L.search(skip=2, limit=2))[0][0]["lid"] == "lic_1"
        assert (await L.search(status="active"))[1] == 1
        assert (await L.search(email="bob"))[1] == 1
        assert (await L.search(lid="LIC_3"))[1] == 1
        assert len(await L.find_same_machine(["c3", "a1", "b2"])) == 2  # lic_1, lic_2；lic_3 分量不同
        assert len(await L.find_same_machine(["a1", "b2"])) == 0
        assert [d["lid"] for d in await L.list_due(100)] == ["lic_2"]
        assert await L.update("lic_1", {"status": "active"}, expect_status=("suspended",)) is None
        assert (await L.get("lic_1"))["status"] == "pending"
        assert (await L.update("lic_1", {"status": "active"}, expect_status=("pending",)))["status"] == "active"
        assert await L.update("nope", {"status": "x"}) is None
    asyncio.run(with_repos(kind, go))


@pytest.mark.parametrize("kind", KINDS)
def test_admins_events_audit_keys(kind):
    async def go(r):
        A = r.admins
        mk = lambda i, u, role="ops", en=True: {"id": i, "username": u, "password_hash": "h", "role": role,
                                                 "enabled": en, "created_at": int(i), "last_login_at": None}
        await A.insert(mk("1", "alice", "super"))
        await A.insert(mk("2", "bob"))
        with pytest.raises(DuplicateError):
            await A.insert(mk("3", "alice"))
        assert (await A.get("2"))["username"] == "bob" and (await A.get_by_username("alice"))["id"] == "1"
        assert await A.count_enabled_super() == 1
        await A.update("1", {"enabled": False})
        assert await A.count_enabled_super() == 0 and len(await A.list()) == 2

        E = r.events
        await E.insert({"lid": "l", "type": "a", "at": 1, "seq": 1})
        await E.insert({"lid": "l", "type": "b", "at": 1, "seq": 2})
        await E.insert({"lid": "m", "type": "c", "at": 1, "seq": 3})
        assert [e["type"] for e in await E.list_for("l")] == ["a", "b"]

        U = r.audit
        for i in range(5):
            await U.insert({"admin_id": "1" if i % 2 else "2", "action": "x" if i < 3 else "y",
                            "target": "t", "before": None, "after": None, "ip": "", "at": 10, "seq": i})
        items, total = await U.search(limit=2)
        assert total == 5 and [i["seq"] for i in items] == [4, 3]
        assert (await U.search(action="y"))[1] == 2 and (await U.search(admin_id="1"))[1] == 2
        assert not hasattr(U, "update") and not hasattr(U, "delete")

        K = r.keys
        await K.upsert("k1", "pub")
        await K.upsert("k1", "pub2", "retired")
        ks = await K.list()
        assert len(ks) == 1 and ks[0]["public_key"] == "pub2" and ks[0]["status"] == "retired"
    asyncio.run(with_repos(kind, go))


@pytest.mark.parametrize("kind", KINDS)
def test_devices_and_leases(kind):
    async def go(r):
        D = r.devices
        dev = lambda lid, did, first, mc=("a", "b"): {"lid": lid, "did": did, "mc": list(mc), "first_seen_at": first,
                                                      "last_seen_at": first, "last_ip": "1.1.1.1", "app_version": "1.0",
                                                      "bound": True, "unbound_at": None}
        await D.insert(dev("l1", "d2", 20))
        await D.insert(dev("l1", "d1", 10))
        await D.insert(dev("l2", "d3", 5))
        assert [d["did"] for d in await D.list_for("l1")] == ["d1", "d2"]
        assert "_id" not in (await D.list_for("l1"))[0]
        up = await D.update("l1", "d1", {"last_ip": "2.2.2.2", "mc": ["a", "c"]})
        assert up["last_ip"] == "2.2.2.2" and up["mc"] == ["a", "c"]
        assert await D.update("l1", "nope", {"last_ip": "x"}) is None
        assert await D.update("l2", "d1", {"last_ip": "x"}) is None  # 不能跨授权更新

        L = r.leases
        assert await L.get("l1", "s1") is None
        await L.upsert("l1", "s1", {"mc": ["a"], "issued_at": 1, "expires_at": 10, "ip": "i"})
        await L.upsert("l1", "s1", {"expires_at": 20})  # 续租只更新，不新增
        await L.upsert("l1", "s2", {"mc": ["a"], "issued_at": 2, "expires_at": 30, "ip": "i"})
        got = await L.get("l1", "s1")
        assert got["expires_at"] == 20 and got["revoked"] is False and "_id" not in got
        assert len(await L.list_for("l1")) == 2
        assert await L.revoke_others("l1", "s2") == 1
        assert (await L.get("l1", "s1"))["revoked"] is True and (await L.get("l1", "s2"))["revoked"] is False
        assert await L.revoke_others("l1", "s2") == 0
    asyncio.run(with_repos(kind, go))
