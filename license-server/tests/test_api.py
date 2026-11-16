import time

import pytest

from dongai_license import license_token as lt
from tests.conftest import PW, comps, issue_body, login, make_admin, mcode

A = "/admin/api"


def issue(client, h, **kw):
    r = client.post(f"{A}/licenses", json=issue_body(**kw), headers=h)
    return r


# ---------- 认证与角色 ----------
def test_health_no_auth(client):
    assert client.get("/health").json() == {"status": "ok"}


@pytest.mark.parametrize("method,path", [
    ("get", "/licenses"), ("post", "/licenses"), ("get", "/licenses/x"), ("post", "/licenses/x/suspend"),
    ("get", "/admins"), ("post", "/admins"), ("get", "/audit"), ("get", "/auth/me")])
def test_unauthenticated_401(client, method, path):
    assert getattr(client, method)(A + path).status_code == 401


def test_bad_token_401(client):
    assert client.get(f"{A}/licenses", headers={"Authorization": "Bearer abc.def.ghi"}).status_code == 401


def test_role_matrix(client, root, ops, ro):
    assert client.get(f"{A}/licenses", headers=ro).status_code == 200
    assert issue(client, ro).status_code == 403
    assert client.post(f"{A}/licenses/x/suspend", headers=ro).status_code == 403
    assert client.get(f"{A}/audit", headers=ro).status_code == 403
    assert client.get(f"{A}/admins", headers=ops).status_code == 403
    assert client.post(f"{A}/admins", headers=ops, json={"username": "zzz", "password": PW, "role": "ops"}).status_code == 403
    assert issue(client, ops).status_code == 201
    assert client.get(f"{A}/audit", headers=ops).status_code == 200
    assert client.get(f"{A}/admins", headers=root).status_code == 200


# ---------- 登录 ----------
def test_login_success_and_me(client, repos):
    make_admin(repos, "root")
    r = client.post(f"{A}/auth/login", json={"username": "ROOT", "password": PW})
    assert r.status_code == 200
    body = r.json()
    assert "password_hash" not in r.text and body["admin"]["last_login_at"]
    from jose import jwt
    claims = jwt.get_unverified_claims(body["token"])
    assert claims["role"] == "super" and claims["admin_id"] and claims["exp"] - claims["iat"] == 8 * 3600
    assert jwt.get_unverified_header(body["token"])["alg"] == "HS256"
    assert client.get(f"{A}/auth/me", headers={"Authorization": "Bearer " + body["token"]}).json()["username"] == "root"


def test_login_failure_indistinguishable(client, repos):
    make_admin(repos, "root")
    a = client.post(f"{A}/auth/login", json={"username": "root", "password": "wrong-wrong-wrong"})
    b = client.post(f"{A}/auth/login", json={"username": "ghost", "password": "wrong-wrong-wrong"})
    assert a.status_code == b.status_code == 401 and a.json() == b.json()


def test_login_lockout(client, repos):
    make_admin(repos, "root")
    for _ in range(5):
        assert client.post(f"{A}/auth/login", json={"username": "root", "password": "x" * 13}).status_code == 401
    r = client.post(f"{A}/auth/login", json={"username": "root", "password": PW})  # 正确密码也被锁
    assert r.status_code == 429 and r.json()["code"] == "LOGIN_LOCKED"
    # 审计里有失败与锁定
    h = None
    # 另一个管理员查审计
    make_admin(repos, "other")
    h = login(client, "other")
    actions = [i["action"] for i in client.get(f"{A}/audit?page_size=100", headers=h).json()["items"]]
    assert actions.count("auth.login_failed") == 5 and "auth.login_locked" in actions


def test_lockout_expires(settings, repos):
    from app.services.security import LoginLimiter
    t = [1000.0]
    lim = LoginLimiter(clock=lambda: t[0])
    k = ("u", "ip")
    for _ in range(5):
        lim.record_failure(k)
    assert lim.locked_for(k) > 0
    t[0] += 901
    assert lim.locked_for(k) == 0
    assert not lim.record_failure(k)  # 解锁后重新计数


def test_disabled_admin_cannot_login_or_use_token(client, repos, root):
    a = make_admin(repos, "oper", "ops")
    h = login(client, "oper")
    assert client.put(f"{A}/admins/{a['id']}", headers=root, json={"enabled": False}).status_code == 200
    assert client.get(f"{A}/licenses", headers=h).status_code == 401
    assert client.post(f"{A}/auth/login", json={"username": "oper", "password": PW}).status_code == 401


# ---------- 签发 ----------
def test_issue_ok_and_verifiable(client, ops, keys):
    r = issue(client, ops, uid="a@b.com")
    assert r.status_code == 201
    lic = r.json()["license"]
    assert lic["lid"].startswith("lic_") and lic["status"] == "pending" and lic["dev_max"] == 1
    assert lic["machine_components"] == comps() and lic["created_by"]
    assert lic["code_display"] and lic["last_seen_at"] is None
    pubs = {keys[2]: keys[1]}
    payload = lt.verify_license(lt.normalize_input(lic["code_display"]), pubs, comps())
    assert payload["lid"] == lic["lid"] and payload["exp"] == lic["expires_at"] and payload["uid"] == "a@b.com"
    assert payload["plan"] == "pro" and payload["features"] == ["video"]
    with pytest.raises(lt.MachineMismatch):
        lt.verify_license(lic["code"], pubs, comps(3, seed=9))
    # 只命中 2 个分量也算同一台机器
    assert lt.verify_license(lic["code"], pubs, comps()[:2] + ["ffffffffffffffff"])


def test_issue_bad_checksum(client, ops):
    mc = mcode()
    bad = mc[:-1] + ("A" if mc[-1] != "A" else "B")
    r = issue(client, ops, machine_code=bad)
    assert r.status_code == 422 and r.json()["code"] == "MACHINE_CODE_INVALID"


def test_issue_too_few_components(client, ops):
    r = issue(client, ops, machine_code=mcode(1))
    assert r.status_code == 422 and r.json()["code"] == "MACHINE_CODE_TOO_FEW"
    assert issue(client, ops, machine_code=mcode(2)).status_code == 201


def test_issue_past_expiry_and_bad_plan(client, ops):
    r = issue(client, ops, expires_at=int(time.time()) - 5)
    assert r.status_code == 422 and r.json()["code"] == "EXPIRES_IN_PAST"
    assert issue(client, ops, plan="nope").json()["code"] == "PLAN_INVALID"
    assert issue(client, ops, features=["Bad Feature"]).json()["code"] == "FEATURE_INVALID"
    assert issue(client, ops, dev_max=0).status_code == 422


def test_issue_iso_expiry(client, ops):
    r = issue(client, ops, expires_at="2099-01-01T00:00:00Z")
    assert r.status_code == 201 and r.json()["license"]["expires_at"] == 4070908800


def test_duplicate_machine_warning(client, ops):
    first = issue(client, ops).json()
    assert first["same_machine_count"] == 0 and first["warnings"] == []
    second = issue(client, ops).json()
    assert second["same_machine_count"] == 1 and "1 条" in second["warnings"][0]
    client.post(f"{A}/licenses/{first['license']['lid']}/revoke", headers=ops)
    third = issue(client, ops).json()
    assert third["same_machine_count"] == 1  # 已吊销的不计
    assert issue(client, ops, machine_code=mcode(3, seed=7)).json()["same_machine_count"] == 0


# ---------- 查询 ----------
def test_list_pagination_search(client, ops):
    for i in range(5):
        issue(client, ops, machine_code=mcode(3, seed=10 + i), email=f"user{i}@Example.com")
    p1 = client.get(f"{A}/licenses?page=1&page_size=2", headers=ops).json()
    assert p1["total"] == 5 and len(p1["items"]) == 2 and "code" not in p1["items"][0]
    p3 = client.get(f"{A}/licenses?page=3&page_size=2", headers=ops).json()
    assert len(p3["items"]) == 1
    ids = {i["lid"] for p in (1, 2, 3) for i in client.get(f"{A}/licenses?page={p}&page_size=2", headers=ops).json()["items"]}
    assert len(ids) == 5
    assert client.get(f"{A}/licenses?email=USER3", headers=ops).json()["total"] == 1
    one = p1["items"][0]["lid"]
    assert client.get(f"{A}/licenses?lid={one}", headers=ops).json()["total"] == 1
    assert client.get(f"{A}/licenses?status=active", headers=ops).json()["total"] == 0
    assert client.get(f"{A}/licenses?status=pending", headers=ops).json()["total"] == 5
    assert client.get(f"{A}/licenses?page_size=1000", headers=ops).status_code == 422
    assert client.get(f"{A}/licenses/lic_nope", headers=ops).status_code == 404


# ---------- 状态机 ----------
def act(client, h, lid):
    # 激活由 L-42 完成，这里直接调内部方法（用 TestClient 的事件循环）
    from app.services.audit import Actor
    return client.portal.call(client.app.state.ctx.licenses.mark_activated, lid, Actor(None, "t"))


def status(client, h, lid):
    return client.get(f"{A}/licenses/{lid}", headers=h).json()["status"]


def post(client, h, lid, action, **body):
    return client.post(f"{A}/licenses/{lid}/{action}", headers=h, json=body or None)


def fresh(client, ops):
    return issue(client, ops, machine_code=mcode(3, seed=int(time.time_ns() % 200))).json()["license"]["lid"]


def test_state_machine_legal_paths(client, ops):
    lid = fresh(client, ops)
    assert status(client, ops, lid) == "pending"
    assert act(client, ops, lid)["status"] == "active"
    assert client.get(f"{A}/licenses/{lid}", headers=ops).json()["activated_at"]
    assert post(client, ops, lid, "suspend").json()["status"] == "suspended"
    assert post(client, ops, lid, "resume").json()["status"] == "active"
    assert post(client, ops, lid, "suspend").status_code == 200
    assert post(client, ops, lid, "revoke").json()["status"] == "revoked"
    types = [e["type"] for e in client.get(f"{A}/licenses/{lid}/events?order=asc", headers=ops).json()["items"]]
    assert types == ["issued", "activated", "suspended", "resumed", "suspended", "revoked"]


@pytest.mark.parametrize("setup,action", [
    ([], "suspend"), ([], "resume"),                       # pending
    (["activate"], "resume"),                              # active 不能 resume
    (["activate", "suspend"], "suspend"),                  # 重复停用
    (["revoke"], "suspend"), (["revoke"], "resume"), (["revoke"], "revoke"),   # 终态
])
def test_state_machine_illegal(client, ops, setup, action):
    lid = fresh(client, ops)
    for s in setup:
        if s == "activate":
            act(client, ops, lid)
        else:
            assert post(client, ops, lid, s).status_code == 200
    before = status(client, ops, lid)
    r = post(client, ops, lid, action)
    assert r.status_code == 409 and r.json()["code"] == "INVALID_TRANSITION"
    assert status(client, ops, lid) == before


def test_revoked_cannot_extend_or_activate(client, ops):
    lid = fresh(client, ops)
    post(client, ops, lid, "revoke")
    r = post(client, ops, lid, "extend", expires_at=int(time.time()) + 999999)
    assert r.status_code == 409
    from app.errors import ApiError
    with pytest.raises(ApiError) as ei:
        act(client, ops, lid)
    assert ei.value.status == 409


def test_mark_activated_twice_409(client, ops):
    from app.errors import ApiError
    lid = fresh(client, ops)
    act(client, ops, lid)
    with pytest.raises(ApiError):
        act(client, ops, lid)


def test_lazy_expiry_and_extend_back_to_active(client, ops, repos, keys):
    lid = fresh(client, ops)
    act(client, ops, lid)
    # 直接把到期时间改到过去，模拟时间流逝
    client.portal.call(repos.licenses.update, lid, {"expires_at": int(time.time()) - 10})
    assert client.get(f"{A}/licenses?status=expired", headers=ops).json()["total"] == 1  # 列表惰性判断
    assert status(client, ops, lid) == "expired"
    assert post(client, ops, lid, "suspend").status_code == 409
    new_exp = int(time.time()) + 5000
    r = post(client, ops, lid, "extend", expires_at=new_exp)
    assert r.status_code == 200 and r.json()["status"] == "active"
    types = [e["type"] for e in client.get(f"{A}/licenses/{lid}/events?order=asc", headers=ops).json()["items"]]
    assert "expired" in types and types[-1] == "extended"


def test_expire_due_method(client, ops, repos):
    lid = fresh(client, ops)
    act(client, ops, lid)
    client.portal.call(repos.licenses.update, lid, {"expires_at": int(time.time()) - 1})
    assert client.portal.call(client.app.state.ctx.licenses.expire_due) == 1
    assert client.portal.call(client.app.state.ctx.licenses.expire_due) == 0


def test_extend_reissues_code(client, ops, keys):
    pubs = {keys[2]: keys[1]}
    first = issue(client, ops).json()["license"]
    lid, old = first["lid"], first["code"]
    new_exp = first["expires_at"] + 86400 * 100
    r = post(client, ops, lid, "extend", expires_at=new_exp)
    assert r.status_code == 200
    got = client.get(f"{A}/licenses/{lid}", headers=ops).json()
    assert got["code"] != old and got["expires_at"] == new_exp and got["code_version"] == 2
    assert lt.verify_license(got["code"], pubs, comps())["exp"] == new_exp
    # 旧码仍能验签，但 exp 是旧值；以服务端记录的最新码为准
    assert lt.verify_license(old, pubs, comps())["exp"] == first["expires_at"]
    ev = [e for e in client.get(f"{A}/licenses/{lid}/events?order=asc", headers=ops).json()["items"] if e["type"] == "extended"][0]
    assert ev["detail"]["code_reissued"] and ev["detail"]["old_code_fp"] != ev["detail"]["new_code_fp"]
    assert old not in str(ev) and got["code"] not in str(ev)
    assert post(client, ops, lid, "extend", expires_at=int(time.time()) - 1).status_code == 422


# ---------- 管理员管理 ----------
def test_admin_crud_and_no_hash(client, root):
    r = client.post(f"{A}/admins", headers=root, json={"username": "newbie", "password": PW, "role": "ops"})
    assert r.status_code == 201 and "password_hash" not in r.text
    aid = r.json()["id"]
    assert "password_hash" not in client.get(f"{A}/admins", headers=root).text
    assert client.post(f"{A}/admins", headers=root, json={"username": "newbie", "password": PW, "role": "ops"}).status_code == 409
    assert client.post(f"{A}/admins", headers=root, json={"username": "short", "password": "short", "role": "ops"}).json()["code"] == "PASSWORD_TOO_SHORT"
    assert client.post(f"{A}/admins", headers=root, json={"username": "bad", "password": PW, "role": "god"}).json()["code"] == "ROLE_INVALID"
    r = client.put(f"{A}/admins/{aid}", headers=root, json={"role": "readonly"})
    assert r.json()["role"] == "readonly" and "password_hash" not in r.text
    # 重置密码：旧密码失效，新密码可登录
    new_pw = "another long password 1"
    assert client.put(f"{A}/admins/{aid}", headers=root, json={"password": new_pw}).status_code == 200
    assert client.post(f"{A}/auth/login", json={"username": "newbie", "password": PW}).status_code == 401
    assert client.post(f"{A}/auth/login", json={"username": "newbie", "password": new_pw}).status_code == 200
    assert client.put(f"{A}/admins/nope", headers=root, json={"enabled": False}).status_code == 404


def test_last_super_protected(client, root, repos):
    me = client.get(f"{A}/auth/me", headers=root).json()["id"]
    assert client.put(f"{A}/admins/{me}", headers=root, json={"enabled": False}).json()["code"] == "LAST_SUPER"
    assert client.put(f"{A}/admins/{me}", headers=root, json={"role": "ops"}).status_code == 409
    second = make_admin(repos, "root2", "super")
    assert client.put(f"{A}/admins/{second['id']}", headers=root, json={"enabled": False}).status_code == 200
    assert client.put(f"{A}/admins/{me}", headers=root, json={"role": "ops"}).status_code == 409  # 又只剩一个
    assert client.put(f"{A}/admins/{second['id']}", headers=root, json={"enabled": True}).status_code == 200
    assert client.put(f"{A}/admins/{me}", headers=root, json={"role": "ops"}).status_code == 200


def test_no_default_admin(client):
    assert client.post(f"{A}/auth/login", json={"username": "admin", "password": "admin"}).status_code == 401
    assert client.get(f"{A}/licenses").status_code == 401


# ---------- 审计 ----------
def test_audit_complete_and_clean(client, root, ops, keys):
    lic = issue(client, ops).json()["license"]
    lid = lic["lid"]
    act(client, ops, lid)
    assert post(client, ops, lid, "suspend").status_code == 200
    assert post(client, ops, lid, "resume").status_code == 200
    post(client, ops, lid, "extend", expires_at=int(time.time()) + 99999)
    post(client, ops, lid, "revoke")
    client.post(f"{A}/admins", headers=root, json={"username": "zed", "password": PW, "role": "readonly"})
    items = client.get(f"{A}/audit?page_size=100", headers=root).json()["items"]
    actions = {i["action"] for i in items}
    assert {"license.issue", "license.activate", "license.suspend", "license.resume", "license.extend", "license.revoke",
            "admin.create", "auth.login_success"} <= actions
    blob = str(items)
    for secret in ("password_hash", "scrypt$", lic["code"], PW, "code_display"):
        assert secret not in blob
    for i in items:
        assert set(i) >= {"admin_id", "action", "target", "before", "after", "ip", "at"}
    iss = next(i for i in items if i["action"] == "license.issue")
    assert iss["target"] == f"license:{lid}" and iss["before"] is None and iss["after"]["lid"] == lid
    assert iss["admin_id"] == client.get(f"{A}/auth/me", headers=ops).json()["id"]
    assert "code" not in iss["after"]
    # 过滤
    only = client.get(f"{A}/audit?action=license.revoke", headers=root).json()
    assert only["total"] == 1
    by_admin = client.get(f"{A}/audit?admin_id={iss['admin_id']}&page_size=100", headers=root).json()
    assert by_admin["total"] >= 4 and all(i["admin_id"] == iss["admin_id"] for i in by_admin["items"])
    assert client.get(f"{A}/audit?page=1&page_size=2", headers=root).json()["items"].__len__() == 2


def test_audit_has_no_mutation_routes(client, root):
    for m in ("put", "patch", "delete", "post"):
        r = getattr(client, m)(f"{A}/audit", headers=root)
        assert r.status_code in (404, 405)
        r = getattr(client, m)(f"{A}/audit/1", headers=root)
        assert r.status_code in (404, 405)


def test_audit_repos_have_no_update_delete():
    from app.repo.base import AuditRepo
    from app.repo.memory import MemAudit
    from app.repo.mongo import MongoAudit
    for cls in (AuditRepo, MemAudit, MongoAudit):
        pub = {n for n in dir(cls) if not n.startswith("_")}
        assert pub <= {"insert", "search", "c"}, pub


def test_responses_never_contain_private_key(client, ops, keys):
    r = issue(client, ops)
    assert keys[0] not in r.text
    assert keys[0] not in client.get(f"{A}/licenses", headers=ops).text
