"""版本管理：管理端 CRUD / 状态机 / 权限 / 审计，客户端 /update，激活与续租的 426 拦截。
内存与 Mongo 两套仓库参数化（Mongo 仅当 LS_MONGO_URL 存在且库名含 test）。"""
import asyncio
import dataclasses
import os

import pytest
from fastapi.testclient import TestClient

from app.config import DbSettings
from app.create_admin import create_admin_in_repo
from app.main import create_app
from app.repo.base import DuplicateError
from app.repo.memory import make_memory_repos
from app.services import semver
from tests.conftest import PW, Clock, comps, issue_body, login
from dongai_license.machine_code import format_machine_code

MONGO_URL = os.environ.get("LS_MONGO_URL")
MONGO_DB = os.environ.get("LS_MONGO_DB", "dongai_license")
mongo_ok = bool(MONGO_URL) and "test" in MONGO_DB.lower()
STORES = ["memory", pytest.param("mongo", marks=pytest.mark.skipif(not mongo_ok, reason="需要 LS_MONGO_URL 且库名含 test"))]
COLS = ("licenses", "admins", "audit_logs", "license_events", "keys", "devices", "leases", "activation_reqs",
        "device_locks", "releases")
MC = comps()
SHA = "a" * 64


def _mongo_run(fn):
    from app.repo.mongo import make_mongo_repos

    async def go():
        r = make_mongo_repos(MONGO_URL, MONGO_DB)
        try:
            await r.ensure_ready()
            return await fn(r)
        finally:
            await r.close()
    return asyncio.run(go())


@pytest.fixture(params=STORES)
def app_client(request, settings, clk):
    """返回 (client, 创建管理员的函数)；每个用例一个干净的库。"""
    if request.param == "memory":
        repos = make_memory_repos()
        with TestClient(create_app(settings, repos, clock=clk)) as c:
            yield c, lambda u, role: asyncio.run(create_admin_in_repo(repos, u, PW, role))
        return
    from pymongo import MongoClient
    mc = MongoClient(MONGO_URL)
    for n in COLS:
        mc[MONGO_DB][n].delete_many({})
    mc.close()
    ms = dataclasses.replace(settings, db=DbSettings(store="mongo", mongo_url=MONGO_URL, mongo_db=MONGO_DB))
    with TestClient(create_app(ms, None, clock=clk)) as c:
        yield c, lambda u, role: _mongo_run(lambda r: create_admin_in_repo(r, u, PW, role))


@pytest.fixture
def api(app_client):
    c, mk = app_client
    mk("root", "super")
    mk("oper", "ops")
    mk("viewer", "readonly")
    c.hroot, c.hops, c.hro = login(c, "root"), login(c, "oper"), login(c, "viewer")
    return c


def body(**kw):
    b = {"version": "1.2.3", "channel": "stable", "platform": "mac-arm64", "notes": "修复若干问题",
         "url": "https://dl.example.com/dongai-1.2.3.dmg", "sha256": SHA, "size": 1234567, "min_supported": None}
    b.update(kw)
    return b


def mk(c, publish=True, **kw):
    r = c.post("/admin/api/releases", json=body(**kw), headers=c.hroot)
    assert r.status_code == 201, r.text
    rid = r.json()["id"]
    if publish:
        p = c.post(f"/admin/api/releases/{rid}/publish", headers=c.hroot)
        assert p.status_code == 200, p.text
    return rid


def upd(c, version, platform="mac-arm64", channel="stable", **kw):
    return c.get("/license/v1/update", params={"version": version, "platform": platform, "channel": channel, **kw})


# ---------- semver ----------
def test_semver_compare():
    assert semver.compare("1.10.0", "1.9.0") == 1
    assert semver.compare("1.2.3+testbuild", "1.2.3") == 0
    assert semver.compare("1.2.3+a", "1.2.3+b") == 0
    assert semver.compare("1.2.3-beta.1", "1.2.3") == -1
    assert semver.compare("1.2.3-beta.2", "1.2.3-beta.10") == -1
    assert semver.compare("2.0.0", "1.99.99") == 1
    for bad in ("1.2", "v1.2.3", "01.2.3", "1.2.3.4", "", "a.b.c", "1.2.3+"):
        assert not semver.is_valid(bad), bad


# ---------- 管理端 ----------
def test_create_get_list(api):
    r = api.post("/admin/api/releases", json=body(sha256="A" * 64), headers=api.hops)
    assert r.status_code == 201, r.text
    rel = r.json()
    assert rel["status"] == "draft" and rel["published_at"] is None and rel["sha256"] == "a" * 64
    assert rel["created_by_username"] == "oper" and rel["id"].startswith("rel_") and "seq" not in rel
    assert api.get(f"/admin/api/releases/{rel['id']}", headers=api.hro).json() == rel
    assert api.get("/admin/api/releases/nope", headers=api.hro).json()["code"] == "RELEASE_NOT_FOUND"
    mk(api, version="1.3.0", channel="beta", platform="win-x64")
    lst = api.get("/admin/api/releases", headers=api.hro).json()
    assert lst["total"] == 2 and lst["items"][0]["version"] == "1.3.0"  # 新建的在前
    f = lambda **q: api.get("/admin/api/releases", params=q, headers=api.hro).json()
    assert f(channel="beta")["total"] == 1 and f(platform="mac-arm64")["total"] == 1
    assert f(status="published")["total"] == 1 and f(status="draft")["total"] == 1
    assert f(page_size=1, page=2)["items"][0]["id"] == rel["id"]
    assert api.get("/admin/api/releases", params={"channel": "x"}, headers=api.hro).status_code == 422
    assert api.get("/admin/api/releases", params={"status": "x"}, headers=api.hro).json()["code"] == "STATUS_INVALID"


@pytest.mark.parametrize("kw,code", [
    ({"version": "1.2"}, "VERSION_INVALID"),
    ({"version": "v1.2.3"}, "VERSION_INVALID"),
    ({"channel": "nightly"}, "CHANNEL_INVALID"),
    ({"platform": "linux"}, "PLATFORM_INVALID"),
    ({"url": "http://dl.example.com/a.dmg"}, "URL_INVALID"),
    ({"url": "ftp://dl.example.com/a.dmg"}, "URL_INVALID"),
    ({"url": "https://"}, "URL_INVALID"),
    ({"url": "https://user:pw@dl.example.com/a.dmg"}, "URL_INVALID"),
    ({"url": "http://127.0.0.1.evil.com/a.dmg"}, "URL_INVALID"),
    ({"sha256": "abc"}, "SHA256_INVALID"),
    ({"sha256": "g" * 64}, "SHA256_INVALID"),
    ({"size": 0}, "SIZE_INVALID"),
    ({"size": -5}, "SIZE_INVALID"),
    ({"min_supported": "x"}, "MIN_SUPPORTED_INVALID"),
    ({"min_supported": "1.2.4"}, "MIN_SUPPORTED_TOO_HIGH"),
    ({"version": "1.2.3", "min_supported": "2.0.0"}, "MIN_SUPPORTED_TOO_HIGH"),
])
def test_create_validation(api, kw, code):
    r = api.post("/admin/api/releases", json=body(**kw), headers=api.hroot)
    assert r.status_code == 422 and r.json()["code"] == code, r.text


def test_url_dev_loopback_and_min_equal(api):
    r = api.post("/admin/api/releases", json=body(url="http://127.0.0.1:9000/a.dmg", min_supported="1.2.3"),
                 headers=api.hroot)
    assert r.status_code == 201, r.text
    assert api.post("/admin/api/releases", json=body(version="1.2.4+build7", min_supported="1.2.4"),
                    headers=api.hroot).status_code == 201


def test_duplicate_version(api):
    mk(api, publish=False)
    r = api.post("/admin/api/releases", json=body(), headers=api.hroot)
    assert r.status_code == 409 and r.json()["code"] == "RELEASE_DUPLICATE"
    # 忽略构建元数据后相同也算重复
    assert api.post("/admin/api/releases", json=body(version="1.2.3+x"), headers=api.hroot).status_code == 409
    # 换平台或渠道不算
    assert api.post("/admin/api/releases", json=body(platform="win-x64"), headers=api.hroot).status_code == 201
    assert api.post("/admin/api/releases", json=body(channel="beta"), headers=api.hroot).status_code == 201


def test_update_draft_only(api):
    rid = mk(api, publish=False)
    r = api.put(f"/admin/api/releases/{rid}", json={"notes": "新说明", "version": "1.2.4", "min_supported": "1.0.0"},
                headers=api.hops)
    assert r.status_code == 200, r.text
    assert r.json()["notes"] == "新说明" and r.json()["version"] == "1.2.4" and r.json()["min_supported"] == "1.0.0"
    assert r.json()["url"].endswith("1.2.3.dmg")  # 未传的字段保持
    # 清空 min_supported
    assert api.put(f"/admin/api/releases/{rid}", json={"min_supported": None}, headers=api.hops).json()["min_supported"] is None
    # 校验沿用：改 version 低于 min_supported
    api.put(f"/admin/api/releases/{rid}", json={"min_supported": "1.2.0"}, headers=api.hops)
    r = api.put(f"/admin/api/releases/{rid}", json={"version": "1.1.0"}, headers=api.hops)
    assert r.status_code == 422 and r.json()["code"] == "MIN_SUPPORTED_TOO_HIGH"
    # 撞版本
    mk(api, publish=False, version="2.0.0")
    r = api.put(f"/admin/api/releases/{rid}", json={"version": "2.0.0"}, headers=api.hops)
    assert r.status_code == 409 and r.json()["code"] == "RELEASE_DUPLICATE"
    # 已发布后一切不可改（version/url/sha256 都在内）
    api.post(f"/admin/api/releases/{rid}/publish", headers=api.hops)
    for kw in ({"version": "9.9.9"}, {"url": "https://x.example.com/a"}, {"sha256": "b" * 64}, {"notes": "x"}):
        r = api.put(f"/admin/api/releases/{rid}", json=kw, headers=api.hops)
        assert r.status_code == 409 and r.json()["code"] == "RELEASE_NOT_DRAFT", kw
    assert api.put("/admin/api/releases/nope", json={"notes": "x"}, headers=api.hops).status_code == 404


def test_state_machine(api):
    rid = mk(api, publish=False)
    # 草稿不能撤回
    r = api.post(f"/admin/api/releases/{rid}/withdraw", headers=api.hroot)
    assert r.status_code == 409 and r.json()["code"] == "INVALID_TRANSITION"
    p = api.post(f"/admin/api/releases/{rid}/publish", headers=api.hroot).json()
    assert p["release"]["status"] == "published" and p["release"]["published_at"] and p["warnings"] == []
    assert api.post(f"/admin/api/releases/{rid}/publish", headers=api.hroot).status_code == 409
    w = api.post(f"/admin/api/releases/{rid}/withdraw", headers=api.hroot).json()
    assert w["release"]["status"] == "withdrawn" and w["release"]["withdrawn_at"]
    # 撤回是终态：不能再发布、再撤回
    assert api.post(f"/admin/api/releases/{rid}/publish", headers=api.hroot).status_code == 409
    assert api.post(f"/admin/api/releases/{rid}/withdraw", headers=api.hroot).status_code == 409
    for act in ("publish", "withdraw"):
        assert api.post(f"/admin/api/releases/nope/{act}", headers=api.hroot).status_code == 404


def test_permissions(api):
    rid = mk(api, publish=False)
    for h in (api.hro, {}):
        want = 403 if h else 401
        assert api.post("/admin/api/releases", json=body(version="3.0.0"), headers=h).status_code == want
        assert api.put(f"/admin/api/releases/{rid}", json={"notes": "x"}, headers=h).status_code == want
        assert api.post(f"/admin/api/releases/{rid}/publish", headers=h).status_code == want
        assert api.post(f"/admin/api/releases/{rid}/withdraw", headers=h).status_code == want
    assert api.get("/admin/api/releases", headers=api.hro).status_code == 200
    assert api.get(f"/admin/api/releases/{rid}", headers=api.hro).status_code == 200
    assert api.get("/admin/api/releases").status_code == 401
    assert api.post("/admin/api/releases", json=body(version="3.0.0"), headers=api.hops).status_code == 201
    assert api.get("/admin/api/meta", headers=api.hro).json()["releases"]["platforms"] == ["mac-arm64", "mac-x64", "win-x64"]


def test_audit_trail(api):
    rid = mk(api, publish=False)
    api.put(f"/admin/api/releases/{rid}", json={"notes": "n2"}, headers=api.hops)
    api.post(f"/admin/api/releases/{rid}/publish", headers=api.hops)
    api.post(f"/admin/api/releases/{rid}/withdraw", headers=api.hroot)
    for action in ("release.create", "release.update", "release.publish", "release.withdraw"):
        items = api.get("/admin/api/audit", params={"action": action}, headers=api.hroot).json()["items"]
        assert len(items) == 1, action
        assert items[0]["target"] == f"release:{rid}" and items[0]["admin_username"]
    pub = api.get("/admin/api/audit", params={"action": "release.publish"}, headers=api.hroot).json()["items"][0]
    assert pub["before"]["status"] == "draft" and pub["after"]["status"] == "published"
    assert pub["admin_username"] == "oper"


def test_withdraw_force_line_warning(api):
    a = mk(api, version="1.0.0")
    b = mk(api, version="1.5.0", min_supported="1.2.0")
    c2 = mk(api, version="1.6.0", min_supported="1.2.0")  # 另一条也提供同样的线
    d = mk(api, version="2.0.0")  # 没有 min_supported
    # b 不是唯一来源：撤回后线不变，无提示
    w = api.post(f"/admin/api/releases/{b}/withdraw", headers=api.hroot).json()
    assert w["warnings"] == [] and w["force_line"] == {"before": "1.2.0", "after": "1.2.0"}
    # 撤回最后一个来源：给提示，线消失
    w = api.post(f"/admin/api/releases/{c2}/withdraw", headers=api.hroot).json()
    assert w["force_line"] == {"before": "1.2.0", "after": None}
    assert len(w["warnings"]) == 1 and "1.2.0" in w["warnings"][0]
    # 撤回不提供强制线的版本：无提示
    assert api.post(f"/admin/api/releases/{d}/withdraw", headers=api.hroot).json()["warnings"] == []
    assert upd(api, "1.1.0").json()["force"] is False
    # 发布抬高强制线时也提示
    e = mk(api, publish=False, version="3.0.0", min_supported="2.5.0")
    p = api.post(f"/admin/api/releases/{e}/publish", headers=api.hroot).json()
    assert p["force_line"] == {"before": None, "after": "2.5.0"} and len(p["warnings"]) == 1
    assert a


# ---------- /license/v1/update ----------
def test_update_no_release(api):
    r = upd(api, "1.0.0")
    assert r.status_code == 200 and r.json() == {"update_available": False, "latest": None, "force": False,
                                                 "min_supported": None}


def test_update_branches(api, clk):
    mk(api, version="1.9.0")
    mk(api, version="1.10.0", notes="新功能")
    mk(api, publish=False, version="2.0.0")  # 草稿不可见
    r = upd(api, "1.9.0").json()
    assert r["update_available"] is True and r["force"] is False and r["min_supported"] is None
    assert r["latest"]["version"] == "1.10.0"  # 1.10.0 > 1.9.0，不是字符串比较
    assert set(r["latest"]) == {"version", "notes", "url", "sha256", "size", "published_at"}
    assert r["latest"]["notes"] == "新功能" and r["latest"]["sha256"] == SHA and r["latest"]["size"] == 1234567
    assert r["latest"]["published_at"] == int(clk.t)
    assert upd(api, "1.10.0").json()["update_available"] is False  # 已是最新
    assert upd(api, "1.10.0+testbuild").json()["update_available"] is False  # 构建元数据忽略
    assert upd(api, "1.9.0+testbuild").json()["update_available"] is True
    assert upd(api, "2.0.0").json()["update_available"] is False  # 比线上新（开发版）
    assert upd(api, "1.10.0-beta.1").json()["update_available"] is True  # 预发布低于同号正式版


def test_update_force(api):
    mk(api, version="1.0.0", min_supported="1.0.0")
    mk(api, version="1.5.0", min_supported="1.2.0")
    mk(api, version="1.6.0", min_supported="1.1.0")
    mk(api, version="2.0.0")
    r = upd(api, "1.1.9").json()
    assert r["force"] is True and r["min_supported"] == "1.2.0" and r["update_available"] is True  # 取最大
    assert upd(api, "1.2.0").json()["force"] is False
    assert upd(api, "1.2.0+test").json()["force"] is False
    assert upd(api, "1.1.9+test").json()["force"] is True
    assert upd(api, "1.10.0").json()["force"] is False


def test_update_withdrawn(api):
    a = mk(api, version="1.0.0")
    b = mk(api, version="1.1.0", min_supported="1.0.0")
    assert upd(api, "0.9.0").json()["force"] is True
    api.post(f"/admin/api/releases/{b}/withdraw", headers=api.hroot)
    r = upd(api, "0.9.0").json()
    assert r["latest"]["version"] == "1.0.0" and r["force"] is False and r["min_supported"] is None
    api.post(f"/admin/api/releases/{a}/withdraw", headers=api.hroot)
    assert upd(api, "0.9.0").json()["latest"] is None


def test_update_channel_platform_isolation(api):
    mk(api, version="1.0.0", channel="stable")
    mk(api, version="1.1.0-beta.1", channel="beta", min_supported="1.0.0")
    mk(api, version="9.0.0", platform="win-x64", min_supported="8.0.0")
    r = upd(api, "0.5.0").json()  # 默认 stable
    assert r["latest"]["version"] == "1.0.0" and r["force"] is False
    r = api.get("/license/v1/update", params={"version": "0.5.0", "platform": "mac-arm64"}).json()
    assert r["latest"]["version"] == "1.0.0"  # 不传 channel 默认 stable
    r = upd(api, "0.5.0", channel="beta").json()
    assert r["latest"]["version"] == "1.1.0-beta.1" and r["force"] is True
    assert upd(api, "0.5.0", platform="mac-x64").json()["latest"] is None
    r = upd(api, "1.0.0", platform="win-x64").json()
    assert r["latest"]["version"] == "9.0.0" and r["force"] is True


def test_update_param_errors_and_open(api):
    assert api.get("/license/v1/update", params={"platform": "mac-arm64"}).status_code == 422
    assert api.get("/license/v1/update", params={"version": "1.0.0"}).status_code == 422
    assert upd(api, "abc").json()["code"] == "VERSION_INVALID"
    assert upd(api, "1.0.0", platform="linux").json()["code"] == "PLATFORM_INVALID"
    assert upd(api, "1.0.0", channel="x").json()["code"] == "CHANNEL_INVALID"
    # 无需登录（api fixture 里的 client 默认不带任何头）
    assert upd(api, "1.0.0").status_code == 200


def test_update_rate_limit(api, clk):
    for _ in range(120):
        assert upd(api, "1.0.0").status_code == 200
    r = upd(api, "1.0.0")
    assert r.status_code == 429 and r.json()["code"] == "RATE_LIMITED"
    clk.advance(61)
    assert upd(api, "1.0.0").status_code == 200


# ---------- 426 ----------
def _license(c):
    r = c.post("/admin/api/licenses", json=issue_body(machine_code=format_machine_code(MC)), headers=c.hroot)
    assert r.status_code == 201, r.text
    return r.json()["license"]["code"]


def _act(c, code, **kw):
    return c.post("/license/v1/activate", json={"license_code": code, "machine_components": MC, **kw})


def _renew(c, lease, **kw):
    return c.post("/license/v1/renew", json={"lease": lease, "machine_components": MC, **kw})


def test_activate_426(api):
    code = _license(api)
    mk(api, version="2.0.0", min_supported="1.5.0")
    r = _act(api, code, app_version="1.4.9", platform="mac-arm64", channel="stable")
    assert r.status_code == 426
    assert r.json() == {"code": "UPDATE_REQUIRED", "message": r.json()["message"], "min_supported": "1.5.0"}
    # 没签发：授权仍是 pending，没有设备、没有会话
    lic = api.get("/admin/api/licenses", headers=api.hroot).json()["items"][0]
    assert lic["status"] == "pending" and lic["active_sid"] is None
    # 刚好等于线、高于线、带构建信息：放行
    assert _act(api, code, app_version="1.5.0", platform="mac-arm64").status_code == 200
    assert _act(api, code, app_version="1.5.1+testbuild", platform="mac-arm64").status_code == 200
    assert _act(api, code, app_version="1.10.0", platform="mac-arm64", channel="stable").status_code == 200
    # 1.5.0+build 视为 1.5.0
    assert _act(api, code, app_version="1.4.9+b5", platform="mac-arm64").status_code == 426


def test_activate_not_blocked_cases(api):
    code = _license(api)
    mk(api, version="2.0.0", min_supported="1.5.0")
    # 老客户端：没有 app_version（或空）/ 没有 platform：不拦截
    assert _act(api, code).status_code == 200
    assert _act(api, code, app_version="").status_code == 200
    assert _act(api, code, app_version="1.0.0").status_code == 200  # 无 platform
    assert _act(api, code, app_version="dev", platform="mac-arm64").status_code == 200  # 非 semver
    assert _act(api, code, app_version="1.0.0", platform="win-x64").status_code == 200  # 其他平台没有线
    assert _act(api, code, app_version="1.0.0", platform="mac-arm64", channel="beta").status_code == 200  # 其他渠道
    assert _act(api, code, app_version="1.0.0", platform="plan9").status_code == 200  # 不认识的平台


def test_activate_426_follows_withdraw_and_draft(api):
    code = _license(api)
    rid = mk(api, version="2.0.0", min_supported="1.5.0", publish=False)
    assert _act(api, code, app_version="1.0.0", platform="mac-arm64").status_code == 200  # 草稿不生效
    api.post(f"/admin/api/releases/{rid}/publish", headers=api.hroot)
    assert _act(api, code, app_version="1.0.0", platform="mac-arm64").status_code == 426
    api.post(f"/admin/api/releases/{rid}/withdraw", headers=api.hroot)
    assert _act(api, code, app_version="1.0.0", platform="mac-arm64").status_code == 200


def test_renew_426(api):
    code = _license(api)
    lease = _act(api, code, app_version="1.0.0", platform="mac-arm64").json()["lease"]
    mk(api, version="2.0.0", min_supported="1.5.0")
    r = _renew(api, lease, app_version="1.0.0", platform="mac-arm64")
    assert r.status_code == 426 and r.json()["code"] == "UPDATE_REQUIRED" and r.json()["min_supported"] == "1.5.0"
    # 没续租：设备版本未更新，租约仍有效（旧租约不受影响，客户端拿到 426 自行处理）
    assert _renew(api, lease, app_version="1.5.0", platform="mac-arm64").status_code == 200
    assert _renew(api, lease, app_version="1.0.0").status_code == 200  # 老客户端不带 platform：放行
    assert _renew(api, lease, app_version="").status_code == 200
    assert _renew(api, lease, app_version="1.0.0", platform="mac-arm64", channel="beta").status_code == 200


def test_renew_426_after_bad_lease_still_normal_error(api):
    mk(api, version="2.0.0", min_supported="1.5.0")
    r = _renew(api, "garbage", app_version="1.0.0", platform="mac-arm64")
    assert r.status_code == 401 and r.json()["code"] == "LICENSE_INVALID"  # 伪造租约不会靠 426 探测


def rel_doc(rid, version="1.0.0", status="draft", **kw):
    d = {"id": rid, "version": version, "channel": "stable", "platform": "mac-arm64", "notes": "", "url": "https://a.example.com/x",
         "sha256": SHA, "size": 1, "min_supported": None, "status": status, "created_at": 1, "seq": 1, "updated_at": 1,
         "published_at": None, "withdrawn_at": None, "created_by": "a", "created_by_username": "a"}
    d.update(kw)
    return d


@pytest.mark.parametrize("kind", STORES)
def test_repo_unique_and_filters(kind):
    """仓库层：(version, channel, platform) 唯一约束在内存与 Mongo 一致；条件更新原子。"""
    async def go(r):
        R = r.releases
        await R.insert(rel_doc("r1"))
        with pytest.raises(DuplicateError):
            await R.insert(rel_doc("r2"))  # 同一 (version, channel, platform)
        await R.insert(rel_doc("r2", channel="beta"))
        await R.insert(rel_doc("r3", version="1.1.0", status="published", created_at=3, seq=3))
        with pytest.raises(DuplicateError):
            await R.update("r3", {"version": "1.0.0"})  # 改版本撞唯一键
        assert await R.update("r3", {"notes": "x"}, expect_status=("draft",)) is None
        assert (await R.update("r3", {"notes": "x"}, expect_status=("published",)))["notes"] == "x"
        assert await R.update("zz", {"notes": "x"}) is None
        assert "_id" not in await R.get("r1")
        rows, total = await R.search(channel="stable", status="published")
        assert total == 1 and rows[0]["id"] == "r3"
        assert len(await R.list_for("stable", "mac-arm64")) == 2
        assert [x["id"] for x in await R.list_for("stable", "mac-arm64", "published")] == ["r3"]
        assert await R.list_for("stable", "win-x64") == []
        rows, total = await R.search(skip=0, limit=1)
        assert total == 3 and rows[0]["id"] == "r3"  # created_at 倒序
    if kind == "memory":
        asyncio.run(go(make_memory_repos()))
        return
    from pymongo import MongoClient
    mc = MongoClient(MONGO_URL)
    mc[MONGO_DB]["releases"].delete_many({})
    mc.close()
    _mongo_run(go)


@pytest.mark.skipif(not mongo_ok, reason="需要 LS_MONGO_URL 且库名含 test")
def test_mongo_concurrent_create_one_wins(settings, clk):
    """并发建同一版本：Mongo 唯一索引兜底，只有一个成功。"""
    from app.repo.mongo import make_mongo_repos
    from app.services.audit import Actor, AuditService
    from app.services.releases import ReleaseService
    from pymongo import MongoClient
    mc = MongoClient(MONGO_URL)
    mc[MONGO_DB]["releases"].delete_many({})
    mc.close()

    async def go(r):
        svc = ReleaseService(r, AuditService(r.audit), clk)
        res = await asyncio.gather(*[svc.create(Actor("a", "ip", "a"), **body()) for _ in range(6)],
                                   return_exceptions=True)
        assert sum(isinstance(x, dict) for x in res) == 1, res
        assert all(getattr(x, "code", "") == "RELEASE_DUPLICATE" for x in res if not isinstance(x, dict)), res
        idx = await r._db["releases"].index_information()
        assert any(v.get("unique") and [k for k, _ in v["key"]] == ["version", "channel", "platform"]
                   for v in idx.values())
    _mongo_run(go)
