"""L-42：激活与设备绑定，以及激活 + 续租的端到端行为。"""
import asyncio
import logging

import pytest

from tests.conftest import comps, issue_body, mcode
from dongai_license import license_token as lt
from dongai_license.machine_code import format_machine_code

MC = comps()
DAY = 86400


def run(coro):
    return asyncio.run(coro)


def issue(client, root, mc=MC, **kw):
    r = client.post("/admin/api/licenses", json=issue_body(machine_code=format_machine_code(mc), **kw), headers=root)
    assert r.status_code == 201, r.text
    lic = r.json()["license"]
    return lic["lid"], lic["code"], lic["code_display"]


def activate(client, code, mc=MC, **kw):
    return client.post("/license/v1/activate", json={"license_code": code, "machine_components": mc,
                                                     "app_version": "1.2.3", **kw})


def renew(client, lease, mc=MC):
    return client.post("/license/v1/renew", json={"lease": lease, "machine_components": mc, "app_version": "1.2.3"})


def pub(client):
    s = client.app.state.ctx.settings
    return {s.signing_kid: s.signing_public_key}


def events(repos, lid):
    return run(repos.events.list_for(lid))


def test_first_activation(client, repos, root, clk):
    lid, code, _ = issue(client, root)
    assert run(repos.licenses.get(lid))["status"] == "pending"
    r = activate(client, code)
    assert r.status_code == 200, r.text
    b = r.json()
    p = lt.verify_lease(b["lease"], pub(client), MC, now=clk.t)
    assert p["lid"] == lid and p["exp"] == b["expires_at"] == int(clk.t) + DAY and len(p["sid"]) >= 16
    assert b["server_time"] == int(clk.t)
    assert b["license"] == {"plan": "pro", "features": ["video"], "expires_at": run(repos.licenses.get(lid))["expires_at"],
                            "status": "active"}
    lic = run(repos.licenses.get(lid))
    assert lic["status"] == "active" and lic["activated_at"] == int(clk.t) and lic["active_sid"] == p["sid"]
    assert lic["last_seen_at"] == int(clk.t) and lic["last_renew_at"] == int(clk.t)
    devs = run(repos.devices.list_for(lid))
    assert len(devs) == 1 and devs[0]["mc"] == MC and devs[0]["bound"] is True and devs[0]["app_version"] == "1.2.3"
    assert devs[0]["first_seen_at"] == int(clk.t)
    lease_row = run(repos.leases.get(lid, p["sid"]))
    assert lease_row["expires_at"] == b["expires_at"] and lease_row["revoked"] is False
    assert [e["type"] for e in events(repos, lid)] == ["issued", "activated", "device_bound"]


def test_display_format_code_accepted(client, root):
    _, _, disp = issue(client, root)
    assert "\n" in disp or "-" in disp
    assert activate(client, disp).status_code == 200


def test_repeat_activation_same_device(client, repos, root, clk):
    lid, code, _ = issue(client, root)
    s1 = lt.verify_lease(activate(client, code).json()["lease"], pub(client), MC, now=clk.t)["sid"]
    clk.advance(60)
    r = activate(client, code)
    assert r.status_code == 200
    s2 = lt.verify_lease(r.json()["lease"], pub(client), MC, now=clk.t)["sid"]
    assert s1 != s2 and len(run(repos.devices.list_for(lid))) == 1
    types = [e["type"] for e in events(repos, lid)]
    assert types.count("activated") == 1 and "renewed" in types and "session_replaced" in types


def test_lease_ttl_env_and_capped(client, repos, root, settings, clk):
    lid, code, _ = issue(client, root, expires_at=int(clk.t) + 5000)
    b = activate(client, code).json()
    assert b["expires_at"] == int(clk.t) + 5000  # 不超过授权到期
    assert b["expires_at"] <= run(repos.licenses.get(lid))["expires_at"]


def test_custom_ttl(settings, repos, clk):
    from dataclasses import replace
    from fastapi.testclient import TestClient
    from app.main import create_app
    from tests import conftest
    conftest.make_admin(repos, "root", "super")
    with TestClient(create_app(replace(settings, lease_ttl_seconds=600), repos, clock=clk)) as c:
        h = conftest.login(c, "root")
        _, code, _ = issue(c, h)
        assert activate(c, code).json()["expires_at"] == int(clk.t) + 600


def test_machine_mismatch_recorded(client, repos, root):
    lid, code, _ = issue(client, root)
    r = activate(client, code, mc=comps(3, seed=9))
    assert r.status_code == 403 and r.json()["code"] == "LICENSE_MACHINE_MISMATCH"
    assert run(repos.licenses.get(lid))["status"] == "pending"
    ev = [e for e in events(repos, lid) if e["type"] == "machine_mismatch"]
    assert len(ev) == 1 and "ip" in ev[0]
    assert code not in repr(ev) and code[:30] not in repr(ev)


def test_one_component_changed_tolerated(client, repos, root, clk):
    lid, code, _ = issue(client, root)
    assert activate(client, code).status_code == 200
    drift = [MC[0], MC[1], "ffff" + "ab" * 6]
    r = activate(client, code, mc=drift)
    assert r.status_code == 200
    assert lt.verify_lease(r.json()["lease"], pub(client), drift, now=clk.t)["mc"] == drift
    devs = run(repos.devices.list_for(lid))
    assert len(devs) == 1 and devs[0]["mc"] == drift  # 设备分量更新为最新
    assert activate(client, code, mc=[MC[0], "x1" * 8, "x2" * 8]).status_code == 403  # 只剩 1 个命中


def test_dev_max_one_blocks_second_device(client, repos, root):
    full = ["a1" * 8, "b2" * 8, "c3" * 8, "d4" * 8]
    lid, code, _ = issue(client, root, mc=full, dev_max=1)
    d1 = ["a1" * 8, "b2" * 8, "x1" * 8, "x2" * 8]  # 与授权命中 2 个
    d2 = ["c3" * 8, "d4" * 8, "y1" * 8, "y2" * 8]  # 与授权命中 2 个，但与设备 1 无交集
    assert activate(client, code, mc=d1).status_code == 200
    r = activate(client, code, mc=d2)
    assert r.status_code == 403 and r.json()["code"] == "LICENSE_MACHINE_MISMATCH"
    ev = [e for e in events(repos, lid) if e["type"] == "machine_mismatch"]
    assert ev and ev[-1]["detail"]["reason"] == "设备数超过上限"
    assert len(run(repos.devices.list_for(lid))) == 1


def test_dev_max_two_allows_second_device(client, repos, root):
    full = ["a1" * 8, "b2" * 8, "c3" * 8, "d4" * 8]
    lid, code, _ = issue(client, root, mc=full, dev_max=2)
    d1 = ["a1" * 8, "b2" * 8, "x1" * 8, "x2" * 8]
    d2 = ["c3" * 8, "d4" * 8, "y1" * 8, "y2" * 8]
    assert activate(client, code, mc=d1).status_code == 200
    assert activate(client, code, mc=d2).status_code == 200
    assert len(run(repos.devices.list_for(lid))) == 2


def test_old_code_rejected_after_extend(client, repos, root, clk):
    lid, old, _ = issue(client, root)
    assert activate(client, old).status_code == 200
    client.post(f"/admin/api/licenses/{lid}/extend", json={"expires_at": int(clk.t) + 90 * DAY}, headers=root)
    new = run(repos.licenses.get(lid))["code"]
    assert new != old
    r = activate(client, old)
    assert r.status_code == 401 and r.json()["code"] == "LICENSE_INVALID"
    ev = [e for e in events(repos, lid) if e["type"] == "activation_rejected"]
    assert ev and ev[-1]["detail"]["reason"] == "旧码" and old not in repr(ev)
    assert activate(client, new).status_code == 200


def test_old_lease_survives_extend(client, repos, root, clk):
    lid, old, _ = issue(client, root)
    lease = activate(client, old).json()["lease"]
    client.post(f"/admin/api/licenses/{lid}/extend", json={"expires_at": int(clk.t) + 90 * DAY}, headers=root)
    assert activate(client, old).status_code == 401  # 旧码不能再激活
    assert renew(client, lease).status_code == 200  # 但已有租约继续续租


def test_tampered_and_garbage_codes(client, root):
    _, code, _ = issue(client, root)
    body, sig = code.split(".")
    bad = body + "." + sig[:-3] + ("AAA" if not sig.endswith("AAA") else "BBB")
    for c in (bad, "garbage", body, code.lower() + "0"):
        r = activate(client, c)
        assert r.status_code == 401 and r.json()["code"] == "LICENSE_INVALID", c


def test_signed_by_other_key_rejected(client, root):
    from dongai_license import crypto
    priv, _ = crypto.generate_keypair()[:2]
    forged = lt.issue_license(priv, client.app.state.ctx.settings.signing_kid, lid="lic_x", mc=MC, plan="pro",
                              features=[], exp=2_000_000_000)
    r = activate(client, forged)
    assert r.status_code == 401 and r.json()["code"] == "LICENSE_INVALID"


def test_valid_signature_unknown_lid(client, root):
    s = client.app.state.ctx.settings
    forged = lt.issue_license(s.signing_private_key, s.signing_kid, lid="lic_nope", mc=MC, plan="pro",
                              features=[], exp=2_000_000_000)
    r = activate(client, forged)
    assert r.status_code == 401 and r.json()["code"] == "LICENSE_INVALID"


def test_expired_license(client, repos, root, clk):
    lid, code, _ = issue(client, root, expires_at=int(clk.t) + 100)
    clk.advance(101)
    r = activate(client, code)
    assert r.status_code == 403 and r.json()["code"] == "LICENSE_EXPIRED"
    assert run(repos.licenses.get(lid))["status"] == "pending"


def test_expired_status_license(client, repos, root, clk):
    lid, code, _ = issue(client, root, expires_at=int(clk.t) + 100)
    assert activate(client, code).status_code == 200
    clk.advance(101)
    assert activate(client, code).json()["code"] == "LICENSE_EXPIRED"


@pytest.mark.parametrize("action,code", [("suspend", "LICENSE_SUSPENDED"), ("revoke", "LICENSE_REVOKED")])
def test_suspended_or_revoked_activate_and_renew(client, repos, root, action, code):
    lid, lcode, _ = issue(client, root)
    lease = activate(client, lcode).json()["lease"]
    assert client.post(f"/admin/api/licenses/{lid}/{action}", headers=root).status_code == 200
    for r in (activate(client, lcode), renew(client, lease)):
        assert r.status_code == 403 and r.json()["code"] == code


def test_revoked_pending_cannot_activate(client, root):
    lid, code, _ = issue(client, root)
    client.post(f"/admin/api/licenses/{lid}/revoke", headers=root)
    assert activate(client, code).json()["code"] == "LICENSE_REVOKED"


def test_single_session_flow(client, repos, root, clk):
    """A 激活 -> B 激活 -> A 续租 409 -> B 续租成功。"""
    lid, code, _ = issue(client, root)
    a = activate(client, code).json()["lease"]
    clk.advance(10)
    b = activate(client, code).json()["lease"]
    r = renew(client, a)
    assert r.status_code == 409 and r.json()["code"] == "LICENSE_SESSION_CONFLICT"
    assert renew(client, b).status_code == 200
    pa = lt.verify_lease(a, pub(client), MC, now=clk.t)
    assert run(repos.leases.get(lid, pa["sid"]))["revoked"] is True


def test_grace_after_activate(client, root, clk):
    _, code, _ = issue(client, root)
    lease = activate(client, code).json()["lease"]
    clk.advance(DAY + 3600)
    assert renew(client, lease).status_code == 200
    lease2 = activate(client, code).json()["lease"]
    clk.advance(DAY + 72 * 3600 + 1)
    r = renew(client, lease2)
    assert r.status_code == 401 and r.json()["code"] == "LEASE_EXPIRED"


def test_status_after_activate(client, root):
    _, code, _ = issue(client, root)
    lease = activate(client, code).json()["lease"]
    r = client.get("/license/v1/status", headers={"Authorization": "Bearer " + lease,
                                                  "X-Machine-Components": ",".join(MC)})
    assert r.status_code == 200 and r.json()["status"] == "active" and r.json()["session_active"] is True


def test_rate_limit_ip(client, root, clk):
    for i in range(20):
        assert activate(client, "garbage").status_code == 401
    r = activate(client, "garbage")
    assert r.status_code == 429 and r.json()["code"] == "RATE_LIMITED"
    clk.advance(61)
    assert activate(client, "garbage").status_code == 401  # 窗口过去后恢复


def test_rate_limit_lid(client, root, clk):
    _, code, _ = issue(client, root)
    for i in range(10):
        assert activate(client, code, mc=comps(3, seed=9)).status_code == 403
    r = activate(client, code)
    assert r.status_code == 429 and r.json()["code"] == "RATE_LIMITED"
    clk.advance(61)
    assert activate(client, code).status_code == 200


def test_validation_and_error_shape(client):
    r = client.post("/license/v1/activate", json={"license_code": "x"})
    assert r.status_code == 422
    r = activate(client, "x", mc=[""])
    assert r.status_code == 400 and set(r.json()) == {"code", "message"}
    r = activate(client, "garbage")
    assert set(r.json()) == {"code", "message"}


def test_logs_and_events_have_no_secrets(client, repos, root, caplog):
    lid, code, disp = issue(client, root)
    with caplog.at_level(logging.DEBUG):
        lease = activate(client, code).json()["lease"]
        activate(client, code, mc=comps(3, seed=9))
        renew(client, lease)
        activate(client, "garbage-" + code[:20])
    text = caplog.text
    sid = lt.verify_lease(lease, pub(client), MC, now=None)["sid"]
    for secret in (code, code[:40], disp.replace("\n", ""), lease, lease[:40], sid):
        assert secret not in text, secret[:10]
    assert lid in text and sid[:6] in text
    assert code[:40] not in repr(events(repos, lid)) and lease[:40] not in repr(events(repos, lid))
    assert sid not in repr(events(repos, lid))  # 事件里同样只有前 6 位


def test_error_messages_do_not_leak(client, root):
    _, code, _ = issue(client, root)
    r = activate(client, code, mc=comps(3, seed=9)).json()
    assert "分量" not in r["message"] and "dev_max" not in r["message"]


# ---- H1：租约内签名字段（lexp/plan/features/cv）

def test_lease_carries_signed_entitlement_on_activate(client, repos, root, clk):
    lid, code, _ = issue(client, root, plan="enterprise", features=["video", "export"])
    lic = run(repos.licenses.get(lid))
    p = lt.verify_lease(activate(client, code).json()["lease"], pub(client), MC, now=clk.t)
    assert p["v"] == 2 and p["lexp"] == lic["expires_at"] and p["plan"] == "enterprise"
    assert p["features"] == sorted(["video", "export"]) and p["cv"] == lic["code_version"] == 1
    assert p["exp"] == int(clk.t) + DAY < p["lexp"]  # 租约 exp 与授权到期 lexp 独立


def test_lease_exp_still_capped_but_lexp_is_license_expiry(client, repos, root, clk):
    exp = int(clk.t) + 7200
    lid, code, _ = issue(client, root, expires_at=exp)
    p = lt.verify_lease(activate(client, code).json()["lease"], pub(client), MC, now=clk.t)
    assert p["exp"] == exp == p["lexp"]


def test_extend_then_renew_gets_new_lexp_and_cv(client, repos, root, clk):
    lid, code, _ = issue(client, root)
    lease = activate(client, code).json()["lease"]
    new_exp = int(clk.t) + 90 * DAY
    assert client.post(f"/admin/api/licenses/{lid}/extend", json={"expires_at": new_exp}, headers=root).status_code == 200
    clk.advance(60)
    p = lt.verify_lease(renew(client, lease).json()["lease"], pub(client), MC, now=clk.t)
    assert p["lexp"] == new_exp and p["cv"] == 2


@pytest.mark.parametrize("plan,features", [("basic", ["video"]), ("pro", ["video", "export", "batch"])])
def test_features_follow_plan(client, repos, root, clk, plan, features):
    lid, code, _ = issue(client, root, plan=plan, features=features)
    p = lt.verify_lease(activate(client, code).json()["lease"], pub(client), MC, now=clk.t)
    assert p["plan"] == plan and p["features"] == sorted(features)
