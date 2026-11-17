"""授权模式下的本地会话（POST /api/auth/local-session）：不连 Mongo，用内存假库 + 假授权客户端。"""
import asyncio
import itertools

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api import auth as auth_api
from api import license as license_api
from core import license_client
from core.license_guard import LicenseGuardMiddleware


class FakeUsers:
    def __init__(self):
        self.docs, self._ids = [], itertools.count(1)

    async def find_one(self, flt):
        for d in self.docs:
            if all(d.get(k) == v for k, v in flt.items()):
                return d
        return None

    async def insert_one(self, doc):
        from bson import ObjectId
        doc["_id"] = ObjectId()
        self.docs.append(doc)
        return type("R", (), {"inserted_id": doc["_id"]})()

    async def update_one(self, flt, update, upsert=False):
        d = await self.find_one(flt)
        if d is None and upsert:
            await self.insert_one(dict(update.get("$setOnInsert", {})))


class FakeDB:
    def __init__(self):
        self.users = FakeUsers()


class StubClient:
    def __init__(self, state):
        self.state = state

    def status(self):
        return {"state": self.state, "plan": "pro", "features": [], "expires_at": None}


@pytest.fixture
def env(monkeypatch):
    monkeypatch.delenv("DONGAI_DESKTOP", raising=False)
    monkeypatch.delenv("DONGAI_LICENSE_DEV", raising=False)
    monkeypatch.delenv("DONGAI_LICENSE_ENFORCE", raising=False)
    db = FakeDB()
    monkeypatch.setattr(auth_api, "get_db", lambda: db)
    app = FastAPI()
    app.include_router(auth_api.router)
    app.include_router(license_api.router)
    app.add_middleware(LicenseGuardMiddleware)
    yield app, db, monkeypatch
    license_client.set_client(None)


def _license_mode(monkeypatch, state, enforce=True):
    monkeypatch.setenv("DONGAI_LICENSE_DEV", "1")
    if enforce:
        monkeypatch.setenv("DONGAI_LICENSE_ENFORCE", "1")
    license_client.set_client(StubClient(state))


@pytest.mark.parametrize("state", ["valid", "grace"])
def test_local_session_ok_and_stable_user(env, state):
    app, db, mp = env
    _license_mode(mp, state)
    c = TestClient(app)
    r1 = c.post("/api/auth/local-session")
    assert r1.status_code == 200, r1.text
    d1 = r1.json()["data"]
    assert d1["token"] and d1["user"]["username"] == auth_api.LOCAL_USERNAME
    r2 = c.post("/api/auth/local-session")
    assert r2.json()["data"]["user"]["id"] == d1["user"]["id"]  # 固定的同一个本地用户
    assert len(db.users.docs) == 1 and db.users.docs[0]["local_license"] is True


def test_local_session_token_works_with_get_current_user(env):
    app, db, mp = env
    _license_mode(mp, "valid")
    token = TestClient(app).post("/api/auth/local-session").json()["data"]["token"]
    from jose import jwt
    from config.settings import settings
    uid = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])["user_id"]
    assert uid == str(db.users.docs[0]["_id"])
    user = asyncio.run(_current_user(token))
    assert user["username"] == auth_api.LOCAL_USERNAME


async def _current_user(token):
    from fastapi.security import HTTPAuthorizationCredentials
    return await auth_api.get_current_user(HTTPAuthorizationCredentials(scheme="Bearer", credentials=token), token="")


@pytest.mark.parametrize("state", ["unactivated", "invalid", "machine_mismatch", "revoked", "session_conflict", "clock_rollback"])
def test_local_session_rejected_without_license(env, state):
    app, db, mp = env
    _license_mode(mp, state)
    r = TestClient(app).post("/api/auth/local-session")
    assert r.status_code == 403 and r.json()["code"] == "LICENSE_REQUIRED"
    assert db.users.docs == []  # 被拒时不会创建本地用户


def test_local_session_rejected_even_without_enforce(env):
    """DEV 模式没开全局拦截时，接口自己也必须校验授权状态"""
    app, db, mp = env
    _license_mode(mp, "unactivated", enforce=False)
    r = TestClient(app).post("/api/auth/local-session")
    assert r.status_code == 403 and r.json()["code"] == "LICENSE_REQUIRED"


def test_local_session_status_check_error_fails_closed(env):
    app, db, mp = env
    _license_mode(mp, "valid")

    class Boom:
        def status(self):
            raise RuntimeError("x")
    license_client.set_client(Boom())
    assert TestClient(app).post("/api/auth/local-session").status_code == 403


@pytest.mark.parametrize("state", ["expired", "suspended", "lease_expired"])
def test_local_session_readonly_states_allowed_through_guard(env, state):
    """只读状态：能拿到会话（用于查看已有数据），业务写操作仍由 license_guard 拦截"""
    app, db, mp = env
    _license_mode(mp, state)
    r = TestClient(app).post("/api/auth/local-session")
    assert r.status_code == 200 and r.json()["data"]["state"] == state
    w = TestClient(app).post("/api/auth/config")  # 其他 POST 仍被只读拦截
    assert w.status_code == 403 and w.json()["code"] == "LICENSE_READONLY"


def test_register_and_login_rejected_in_license_mode(env):
    app, db, mp = env
    _license_mode(mp, "valid")
    c = TestClient(app)
    r = c.post("/api/auth/register", json={"username": "someone", "password": "pass-123456"})
    assert r.status_code == 403 and "授权码" in r.json()["detail"]
    r = c.post("/api/auth/login", json={"username": "someone", "password": "pass-123456"})
    assert r.status_code == 403 and "授权码" in r.json()["detail"]
    assert db.users.docs == []


def test_local_user_cannot_login_by_password_even_outside_license_mode(env):
    app, db, mp = env
    _license_mode(mp, "valid")
    c = TestClient(app)
    c.post("/api/auth/local-session")
    mp.delenv("DONGAI_LICENSE_DEV")
    mp.delenv("DONGAI_LICENSE_ENFORCE")
    r = c.post("/api/auth/login", json={"username": auth_api.LOCAL_USERNAME, "password": "whatever-123"})
    assert r.status_code == 401


def test_non_license_mode_unchanged(env):
    app, db, mp = env
    c = TestClient(app)
    assert c.post("/api/auth/local-session").status_code == 404
    r = c.post("/api/auth/register", json={"username": "normal_user", "password": "pass-123456"})
    assert r.status_code == 200 and r.json()["data"]["token"]
    r = c.post("/api/auth/login", json={"username": "normal_user", "password": "pass-123456"})
    assert r.status_code == 200
    assert c.get("/api/license/status").json()["local_session"] is False


def test_status_exposes_local_session_flag(env):
    app, db, mp = env
    _license_mode(mp, "unactivated")
    assert TestClient(app).get("/api/license/status").json()["local_session"] is True
