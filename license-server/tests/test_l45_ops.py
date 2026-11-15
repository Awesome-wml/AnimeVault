"""L-45：设备管理、踢下线、解绑、申请单、extend 对 expired 的行为。

场景写成函数（只走 HTTP，必要时用 portal 直接改仓库），内存版在本文件跑，Mongo 版在 test_mongo_integration.py 复用。
"""
import time

from tests.conftest import comps, issue_body, mcode
from dongai_license.machine_code import format_machine_code

A = "/admin/api"
MC = comps()
DAY = 86400


def _issue(c, h, **kw):
    r = c.post(f"{A}/licenses", json=issue_body(**kw), headers=h)
    assert r.status_code == 201, r.text
    return r.json()["license"]


def _activate(c, code, mc=MC):
    return c.post("/license/v1/activate", json={"license_code": code, "machine_components": mc,
                                                "app_version": "1.2.3"})


def _renew(c, lease, mc=MC):
    return c.post("/license/v1/renew", json={"lease": lease, "machine_components": mc, "app_version": "1.2.3"})


def _types(c, h, lid):
    return [e["type"] for e in c.get(f"{A}/licenses/{lid}/events?order=asc", headers=h).json()["items"]]


def scenario_devices_kick_unbind(c, h):
    lic = _issue(c, h["ops"])
    lid = lic["lid"]
    assert c.get(f"{A}/licenses/{lid}/devices", headers=h["ro"]).json()["items"] == []
    lease = _activate(c, lic["code"]).json()["lease"]

    devs = c.get(f"{A}/licenses/{lid}/devices", headers=h["ro"]).json()["items"]
    assert len(devs) == 1
    d = devs[0]
    assert d["components_count"] == 3 and d["bound"] is True and d["is_current"] is True
    assert d["components_hint"] == [x[:6] for x in MC] and d["app_version"] == "1.2.3"
    assert "last_ip" in d and d["first_seen_at"] and d["last_seen_at"] and d["unbound_at"] is None
    assert not any(x in str(d) for x in MC)  # 不返回原始分量哈希全文
    assert "mc" not in d
    assert c.get(f"{A}/licenses/nope/devices", headers=h["ro"]).status_code == 404

    # 权限：readonly 不能写
    assert c.post(f"{A}/licenses/{lid}/kick", headers=h["ro"]).status_code == 403
    assert c.post(f"{A}/licenses/{lid}/devices/{d['did']}/unbind", headers=h["ro"]).status_code == 403
    assert c.post(f"{A}/licenses/{lid}/kick").status_code == 401

    # 踢下线
    r = c.post(f"{A}/licenses/{lid}/kick", headers=h["ops"])
    assert r.status_code == 200 and r.json()["active_sid"] is None
    assert "code" not in r.json()
    r = _renew(c, lease)
    assert r.status_code == 409 and r.json()["code"] == "LICENSE_SESSION_CONFLICT"
    st = c.get("/license/v1/status", headers={"Authorization": "Bearer " + lease,
                                              "X-Machine-Components": ",".join(MC)}).json()
    assert st["session_active"] is False
    evs = c.get(f"{A}/licenses/{lid}/events?order=asc", headers=h["ops"]).json()["items"]
    kicked = next(e for e in evs if e["type"] == "session_kicked")
    assert kicked["actor_username"] == "oper" and kicked["detail"]["leases_revoked"] == 1
    assert c.post(f"{A}/licenses/{lid}/kick", headers=h["ops"]).status_code == 409  # 已无会话
    audit = c.get(f"{A}/audit?action=license.kick", headers=h["root"]).json()
    assert audit["total"] == 1 and audit["items"][0]["admin_username"] == "oper"

    # 用授权码重新激活即可恢复
    a = _activate(c, lic["code"])
    assert a.status_code == 200, a.text
    lease2 = a.json()["lease"]
    assert _renew(c, lease2).status_code == 200
    assert len(c.get(f"{A}/licenses/{lid}/devices", headers=h["ro"]).json()["items"]) == 1  # 同一设备

    # 解绑当前会话设备：同时踢下线
    did = d["did"]
    r = c.post(f"{A}/licenses/{lid}/devices/{did}/unbind", headers=h["ops"])
    assert r.status_code == 200, r.text
    assert r.json()["kicked"] is True and r.json()["device"]["bound"] is False and r.json()["device"]["unbound_at"]
    assert _renew(c, lease2).json()["code"] == "LICENSE_SESSION_CONFLICT"
    devs = c.get(f"{A}/licenses/{lid}/devices", headers=h["ro"]).json()["items"]
    assert devs[0]["bound"] is False and devs[0]["is_current"] is False
    assert c.post(f"{A}/licenses/{lid}/devices/{did}/unbind", headers=h["ops"]).json()["code"] == "DEVICE_NOT_BOUND"
    assert c.post(f"{A}/licenses/{lid}/devices/dev_none/unbind", headers=h["ops"]).status_code == 404
    types = _types(c, h["ops"], lid)
    assert types.count("session_kicked") == 2 and "device_unbound" in types
    ub = c.get(f"{A}/audit?action=license.device_unbind", headers=h["root"]).json()["items"][0]
    assert ub["admin_username"] == "oper" and ub["after"]["kicked"] is True

    # 解绑后重新激活：绑定为新的设备记录
    assert _activate(c, lic["code"]).status_code == 200
    devs = c.get(f"{A}/licenses/{lid}/devices", headers=h["ro"]).json()["items"]
    assert [x["bound"] for x in devs] == [False, True]


def scenario_kick_revoked(c, h):
    lic = _issue(c, h["ops"])
    _activate(c, lic["code"])
    c.post(f"{A}/licenses/{lic['lid']}/revoke", headers=h["ops"])
    r = c.post(f"{A}/licenses/{lic['lid']}/kick", headers=h["ops"])
    assert r.status_code == 409 and r.json()["code"] == "INVALID_TRANSITION"


def scenario_requests(c, h):
    body = {"email": "Buyer@Example.com", "machine_code": mcode(3, seed=7), "note": "新电脑"}
    assert c.post("/license/v1/request", json=body).json() == {"status": "pending"}
    # 同邮箱 + 同机器码未处理：去重
    assert c.post("/license/v1/request", json={**body, "email": "buyer@example.com"}).status_code == 200
    lst = c.get(f"{A}/requests?status=pending", headers=h["ops"]).json()
    assert lst["total"] == 1 and lst["page"] == 1
    req = lst["items"][0]
    assert req["email"] == "buyer@example.com" and req["note"] == "新电脑" and req["status"] == "pending"
    assert req["machine_code"] == body["machine_code"] and req["components_count"] == 3
    # 不同机器码是另一张单
    c.post("/license/v1/request", json={**body, "machine_code": mcode(3, seed=8)})
    assert c.get(f"{A}/requests", headers=h["root"]).json()["total"] == 2
    c.app.state.ctx.requests.limiter._hits.clear()  # 限流另有专门用例，这里清零避免干扰
    # 校验
    assert c.post("/license/v1/request", json={**body, "email": "bad"}).json()["code"] == "EMAIL_INVALID"
    assert c.post("/license/v1/request", json={**body, "machine_code": "XXXX"}).status_code == 422
    r = c.post("/license/v1/request", json={**body, "machine_code": format_machine_code(comps(1, 9))})
    assert r.status_code == 422 and r.json()["code"] in ("MACHINE_CODE_TOO_FEW", "MACHINE_CODE_INVALID")
    assert c.post("/license/v1/request", json={"email": "a@b.co"}).status_code == 422

    # 权限
    assert c.get(f"{A}/requests", headers=h["ro"]).status_code == 403
    assert c.post(f"{A}/requests/{req['id']}/reject", headers=h["ro"]).status_code == 403
    assert c.post(f"{A}/requests/{req['id']}/issue", headers=h["ro"],
                  json={"plan": "pro", "expires_at": int(time.time()) + DAY}).status_code == 403
    assert c.get(f"{A}/requests").status_code == 401

    # 签发：复用现有校验，失败时申请单仍是 pending
    exp = int(time.time()) + 30 * DAY
    r = c.post(f"{A}/requests/{req['id']}/issue", headers=h["ops"], json={"plan": "nope", "expires_at": exp})
    assert r.status_code == 422 and r.json()["code"] == "PLAN_INVALID"
    r = c.post(f"{A}/requests/{req['id']}/issue", headers=h["ops"], json={"plan": "pro", "expires_at": 5})
    assert r.status_code == 422 and r.json()["code"] == "EXPIRES_IN_PAST"
    assert c.get(f"{A}/requests?status=pending", headers=h["ops"]).json()["total"] == 2
    r = c.post(f"{A}/requests/{req['id']}/issue", headers=h["ops"],
               json={"plan": "pro", "features": ["video"], "expires_at": exp, "dev_max": 2})
    assert r.status_code == 201, r.text
    lic = r.json()["license"]
    assert lic["email"] == "buyer@example.com" and lic["dev_max"] == 2 and lic["code"]
    assert lic["note"] == "新电脑" and lic["created_by_username"] == "oper"
    assert r.json()["request"]["status"] == "issued" and r.json()["request"]["lid"] == lic["lid"]
    assert r.json()["request"]["handled_by_username"] == "oper"
    assert c.get(f"{A}/licenses/{lic['lid']}", headers=h["ops"]).json()["status"] == "pending"
    assert c.get(f"{A}/licenses?email=buyer@example.com", headers=h["ops"]).json()["total"] == 1
    # 签发出的授权码可激活（机器码就是申请时提交的）
    assert _activate(c, lic["code"], comps(3, 7)).status_code == 200
    # 已处理的不能再处理
    r = c.post(f"{A}/requests/{req['id']}/issue", headers=h["ops"], json={"plan": "pro", "expires_at": exp})
    assert r.status_code == 409 and r.json()["code"] == "REQUEST_NOT_PENDING"
    assert c.post(f"{A}/requests/{req['id']}/reject", headers=h["ops"]).status_code == 409
    assert c.post(f"{A}/requests/req_none/reject", headers=h["ops"]).status_code == 404
    assert c.get(f"{A}/requests?status=issued", headers=h["ops"]).json()["total"] == 1

    # 驳回
    other = c.get(f"{A}/requests?status=pending", headers=h["ops"]).json()["items"][0]
    r = c.post(f"{A}/requests/{other['id']}/reject", headers=h["ops"], json={"reason": "信息不全"})
    assert r.status_code == 200 and r.json()["status"] == "rejected" and r.json()["reason"] == "信息不全"
    assert c.post(f"{A}/requests/{other['id']}/issue", headers=h["ops"],
                  json={"plan": "pro", "expires_at": exp}).status_code == 409
    assert c.get(f"{A}/requests?status=bogus", headers=h["ops"]).status_code == 422
    c.app.state.ctx.requests.limiter._hits.clear()
    # 处理后同邮箱+同机器码可再次提交
    assert c.post("/license/v1/request", json={**body, "machine_code": mcode(3, seed=8)}).status_code == 200
    assert c.get(f"{A}/requests?status=pending", headers=h["ops"]).json()["total"] == 1
    # 分页
    p = c.get(f"{A}/requests?page=1&page_size=1", headers=h["ops"]).json()
    assert p["total"] == 3 and len(p["items"]) == 1 and p["page_size"] == 1
    # 审计
    acts = {i["action"]: i for i in c.get(f"{A}/audit?page_size=100", headers=h["root"]).json()["items"]
            if i["action"].startswith("request.")}
    assert acts["request.issue"]["admin_username"] == "oper" and acts["request.issue"]["after"]["lid"] == lic["lid"]
    assert acts["request.reject"]["after"]["reason"] == "信息不全"


def scenario_request_rate_limit(c, clk):
    for i in range(5):
        r = c.post("/license/v1/request", json={"email": f"u{i}@example.com", "machine_code": mcode(3, seed=20 + i)})
        assert r.status_code == 200, r.text
    r = c.post("/license/v1/request", json={"email": "u9@example.com", "machine_code": mcode(3, seed=40)})
    assert r.status_code == 429 and r.json()["code"] == "RATE_LIMITED"
    clk.advance(3601)
    r = c.post("/license/v1/request", json={"email": "u9@example.com", "machine_code": mcode(3, seed=40)})
    assert r.status_code == 200


def scenario_extend_expired(c, h):
    ctx = c.app.state.ctx
    repo = ctx.repos.licenses
    new_exp = int(time.time()) + 90 * DAY
    # 曾经激活过 -> expired -> 延期回到 active
    a = _issue(c, h["ops"])
    _activate(c, a["code"])
    c.portal.call(repo.update, a["lid"], {"status": "expired"})
    r = c.post(f"{A}/licenses/{a['lid']}/extend", json={"expires_at": new_exp}, headers=h["ops"])
    assert r.json()["status"] == "active"
    # 从未激活却是 expired 的记录（历史/外部写入）-> 延期后仍待激活
    b = _issue(c, h["ops"], machine_code=mcode(3, seed=2))
    c.portal.call(repo.update, b["lid"], {"status": "expired", "expires_at": int(time.time()) - 5})
    r = c.post(f"{A}/licenses/{b['lid']}/extend", json={"expires_at": new_exp}, headers=h["ops"])
    assert r.status_code == 200 and r.json()["status"] == "pending" and r.json()["activated_at"] is None
    ev = [e for e in c.get(f"{A}/licenses/{b['lid']}/events", headers=h["ops"]).json()["items"]
          if e["type"] == "extended"][0]
    assert ev["detail"]["from"] == "expired" and ev["detail"]["to"] == "pending"
    assert _activate(c, r.json()["code"], comps(3, 2)).status_code == 200  # 延期后仍需激活，且能激活
    # pending 到期未激活：保持 pending（惰性到期只处理 active），延期后仍是 pending
    d = _issue(c, h["ops"], machine_code=mcode(3, seed=3))
    c.portal.call(repo.update, d["lid"], {"expires_at": int(time.time()) - 5})
    assert c.get(f"{A}/licenses/{d['lid']}", headers=h["ops"]).json()["status"] == "pending"
    r = c.post(f"{A}/licenses/{d['lid']}/extend", json={"expires_at": new_exp}, headers=h["ops"])
    assert r.json()["status"] == "pending"
    # revoked 仍不可延期
    c.post(f"{A}/licenses/{d['lid']}/revoke", headers=h["ops"])
    assert c.post(f"{A}/licenses/{d['lid']}/extend", json={"expires_at": new_exp}, headers=h["ops"]).status_code == 409


def test_devices_kick_unbind(client, root, ops, ro):
    scenario_devices_kick_unbind(client, {"root": root, "ops": ops, "ro": ro})


def test_kick_revoked(client, root, ops, ro):
    scenario_kick_revoked(client, {"root": root, "ops": ops, "ro": ro})


def test_requests(client, root, ops, ro):
    scenario_requests(client, {"root": root, "ops": ops, "ro": ro})


def test_request_rate_limit(client, clk):
    scenario_request_rate_limit(client, clk)


def test_extend_expired(client, root, ops, ro):
    scenario_extend_expired(client, {"root": root, "ops": ops, "ro": ro})
