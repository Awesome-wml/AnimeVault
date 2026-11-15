"""L-40：租约续租与状态查询。激活流程在 test_activate.py，这里直接把授权置为已激活、手工签租约。"""
import asyncio
import logging
import time

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import comps, issue_body
from dongai_license import license_token as lt

MC = comps()
DAY = 86400


def run(coro):
    return asyncio.run(coro)


def seed(client, repos, root, sid="sidAAA111", **kw):
    """签发并直接置为 active（绕过激活接口），返回 (lid, 租约)。"""
    r = client.post("/admin/api/licenses", json=issue_body(**kw), headers=root)
    assert r.status_code == 201, r.text
    lid = r.json()["license"]["lid"]
    run(repos.licenses.update(lid, {"status": "active", "active_sid": sid, "activated_at": int(time.time())}))  # 真实激活流程必写 activated_at
    return lid, lease_of(client, lid, sid, repos)


def lease_of(client, lid, sid, repos, mc=MC):
    c = client.app.state.ctx
    lic = run(repos.licenses.get(lid))
    return c.client.sign_lease(lic, sid, mc)[0]


def renew(client, lease, mc=MC, **kw):
    return client.post("/license/v1/renew", json={"lease": lease, "machine_components": mc,
                                                  "app_version": "1.0.0", **kw})


def test_renew_ok(client, repos, root, keys, clk):
    lid, lease = seed(client, repos, root)
    clk.advance(3600)
    r = renew(client, lease)
    assert r.status_code == 200, r.text
    b = r.json()
    p = lt.verify_lease(b["lease"], {keys[2]: keys[1]}, MC, now=clk.t)
    assert p["lid"] == lid and p["sid"] == "sidAAA111" and p["exp"] == b["expires_at"] == int(clk.t) + DAY
    assert b["server_time"] == int(clk.t)
    assert b["license"]["plan"] == "pro" and b["license"]["features"] == ["video"] and b["license"]["status"] == "active"
    lic = run(repos.licenses.get(lid))
    assert lic["last_seen_at"] == lic["last_renew_at"] == int(clk.t) and lic["last_seen_ip"] is not None
    ls = run(repos.leases.get(lid, "sidAAA111"))
    assert ls["expires_at"] == b["expires_at"] and not ls["revoked"]


def test_lease_ttl_capped_by_license_expiry(client, repos, root, clk):
    lid, _ = seed(client, repos, root, expires_at=int(clk.t) + 7200)
    lease = lease_of(client, lid, "sidAAA111", repos)
    assert lt.verify_lease(lease, {client.app.state.ctx.settings.signing_kid: client.app.state.ctx.settings.signing_public_key},
                           MC, now=clk.t)["exp"] == int(clk.t) + 7200
    clk.advance(3600)
    b = renew(client, lease).json()
    assert b["expires_at"] == int(clk.t) + 3600  # 只剩 1 小时，不超过授权到期


def test_expired_lease_within_grace_can_renew(client, repos, root, clk):
    lid, lease = seed(client, repos, root)
    clk.advance(DAY + 3600)  # 租约已过期 1 小时
    assert renew(client, lease).status_code == 200
    # 过期 + 72 小时整：拒绝
    lid2, lease2 = seed(client, repos, root, sid="sidBBB222")
    clk.advance(DAY + 72 * 3600)
    r = renew(client, lease2)
    assert r.status_code == 401 and r.json()["code"] == "LEASE_EXPIRED"


def test_grace_boundary(client, repos, root, clk):
    _, lease = seed(client, repos, root)
    clk.advance(DAY + 72 * 3600 - 1)
    assert renew(client, lease).status_code == 200
    _, lease = seed(client, repos, root, sid="sidBBB222")
    clk.advance(DAY + 72 * 3600)
    assert renew(client, lease).json()["code"] == "LEASE_EXPIRED"


def test_session_conflict(client, repos, root):
    lid, lease_a = seed(client, repos, root, sid="sidAAA111")
    run(repos.licenses.update(lid, {"active_sid": "sidBBB222"}))  # 另一会话激活
    r = renew(client, lease_a)
    assert r.status_code == 409 and r.json()["code"] == "LICENSE_SESSION_CONFLICT"
    assert renew(client, lease_of(client, lid, "sidBBB222", repos)).status_code == 200


def test_legacy_license_without_active_sid_is_conflict(client, repos, root):
    lid, lease = seed(client, repos, root)
    run(repos.licenses.update(lid, {"active_sid": None}))
    assert renew(client, lease).status_code == 409


@pytest.mark.parametrize("action,status,code", [("suspend", 403, "LICENSE_SUSPENDED"), ("revoke", 403, "LICENSE_REVOKED")])
def test_admin_actions_block_renew(client, repos, root, action, status, code):
    lid, lease = seed(client, repos, root)
    assert renew(client, lease).status_code == 200
    assert client.post(f"/admin/api/licenses/{lid}/{action}", headers=root).status_code == 200
    r = renew(client, lease)
    assert r.status_code == status and r.json()["code"] == code


def test_resume_allows_renew_again(client, repos, root):
    lid, lease = seed(client, repos, root)
    client.post(f"/admin/api/licenses/{lid}/suspend", headers=root)
    assert renew(client, lease).json()["code"] == "LICENSE_SUSPENDED"
    client.post(f"/admin/api/licenses/{lid}/resume", headers=root)
    assert renew(client, lease).status_code == 200


def test_extend_keeps_existing_lease_renewable(client, repos, root, clk):
    lid, lease = seed(client, repos, root)
    old_code = run(repos.licenses.get(lid))["code"]
    r = client.post(f"/admin/api/licenses/{lid}/extend", json={"expires_at": int(clk.t) + 90 * DAY}, headers=root)
    assert r.status_code == 200
    assert run(repos.licenses.get(lid))["code"] != old_code  # 重签了授权码
    b = renew(client, lease).json()  # 续租不看授权码
    assert b["license"]["expires_at"] == int(clk.t) + 90 * DAY


def test_license_expired(client, repos, root, clk):
    lid, lease = seed(client, repos, root, expires_at=int(clk.t) + 3600)
    clk.advance(3601)
    r = renew(client, lease)
    assert r.status_code == 403 and r.json()["code"] == "LICENSE_EXPIRED"
    assert run(repos.licenses.get(lid))["status"] == "expired"  # 顺带惰性置为 expired


def test_expired_status_blocks_even_if_extended_back_needed(client, repos, root, clk):
    lid, lease = seed(client, repos, root, expires_at=int(clk.t) + 3600)
    clk.advance(3601)
    run(client.app.state.ctx.licenses.expire_due())
    assert renew(client, lease).json()["code"] == "LICENSE_EXPIRED"
    client.post(f"/admin/api/licenses/{lid}/extend", json={"expires_at": int(clk.t) + 10 * DAY}, headers=root)
    assert renew(client, lease).status_code == 200  # 延期后恢复为 active，同会话仍可续


def test_machine_mismatch_and_tolerance(client, repos, root):
    lid, lease = seed(client, repos, root)
    r = renew(client, lease, mc=comps(3, seed=9))
    assert r.status_code == 403 and r.json()["code"] == "LICENSE_MACHINE_MISMATCH"
    drift = [MC[0], MC[1], "ffff" + "ab" * 6]  # 换了 1 个分量，仍容差命中
    b = renew(client, lease, mc=drift)
    assert b.status_code == 200
    p = lt.verify_lease(b.json()["lease"], {client.app.state.ctx.settings.signing_kid: client.app.state.ctx.settings.signing_public_key},
                        drift, now=time.time())
    assert p["mc"] == drift  # 新租约绑定最新分量


@pytest.mark.parametrize("mangle", [lambda t: t[:-4] + ("AAAA" if not t.endswith("AAAA") else "BBBB"),
                                    lambda t: "garbage", lambda t: t.split(".")[0], lambda t: ""])
def test_bad_lease(client, repos, root, mangle):
    _, lease = seed(client, repos, root)
    r = client.post("/license/v1/renew", json={"lease": mangle(lease) or " ", "machine_components": MC, "app_version": "1"})
    assert r.status_code in (401, 422)
    if r.status_code == 401:
        assert r.json()["code"] == "LICENSE_INVALID"


def test_license_code_is_not_a_lease(client, repos, root):
    r = client.post("/admin/api/licenses", json=issue_body(), headers=root)
    code = r.json()["license"]["code"]
    r = renew(client, code)
    assert r.status_code == 401 and r.json()["code"] == "LICENSE_INVALID"


def test_renew_event_throttled(client, repos, root, clk):
    lid, lease = seed(client, repos, root)
    types = lambda: [e["type"] for e in run(repos.events.list_for(lid))]
    renew(client, lease); renew(client, lease)
    assert types().count("renewed") == 1
    clk.advance(1800); renew(client, lease)
    assert types().count("renewed") == 1
    clk.advance(1801); renew(client, lease)
    assert types().count("renewed") == 2


def test_status_endpoint(client, repos, root, clk):
    lid, lease = seed(client, repos, root)
    h = {"Authorization": "Bearer " + lease, "X-Machine-Components": ",".join(MC)}
    r = client.get("/license/v1/status", headers=h)
    assert r.status_code == 200
    b = r.json()
    assert b["status"] == "active" and b["plan"] == "pro" and b["session_active"] is True
    assert b["lease_expires_at"] == int(clk.t) + DAY
    assert run(repos.licenses.get(lid))["last_renew_at"] is None  # 不续租、不改 last_seen
    client.post(f"/admin/api/licenses/{lid}/suspend", headers=root)
    assert client.get("/license/v1/status", headers=h).json()["status"] == "suspended"
    assert client.get("/license/v1/status", headers={**h, "X-Machine-Components": ",".join(comps(3, 7))}).status_code == 403
    assert client.get("/license/v1/status", headers={"X-Machine-Components": ",".join(MC)}).status_code == 401
    assert client.get("/license/v1/status", headers={"Authorization": "Bearer " + lease}).status_code == 400


def test_status_reports_session_replaced(client, repos, root):
    lid, lease = seed(client, repos, root)
    run(repos.licenses.update(lid, {"active_sid": "other"}))
    h = {"Authorization": "Bearer " + lease, "X-Machine-Components": ",".join(MC)}
    assert client.get("/license/v1/status", headers=h).json()["session_active"] is False


def test_logs_have_no_secrets(client, repos, root, caplog):
    lid, lease = seed(client, repos, root)
    with caplog.at_level(logging.DEBUG):
        renew(client, lease)
        run(repos.licenses.update(lid, {"active_sid": "zzzzzzzzzz"}))
        renew(client, lease)
    text = caplog.text
    assert lease not in text and lease.split(".")[0] not in text and "sidAAA111" not in text
    assert lid in text and "sidAAA" in text


def test_expire_loop_runs(settings, repos, clk):
    from dataclasses import replace
    s = replace(settings, expire_interval_seconds=1)
    from tests import conftest
    conftest.make_admin(repos, "root", "super")
    with TestClient(create_app(s, repos, clock=clk)) as c:
        h = conftest.login(c, "root")
        r = c.post("/admin/api/licenses", json=issue_body(expires_at=int(clk.t) + 100), headers=h)
        lid = r.json()["license"]["lid"]
        run(repos.licenses.update(lid, {"status": "active"}))
        clk.advance(200)
        for _ in range(40):
            time.sleep(0.1)
            if run(repos.licenses.get(lid))["status"] == "expired":
                break
        assert run(repos.licenses.get(lid))["status"] == "expired"
