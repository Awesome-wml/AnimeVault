"""L-45：审计/事件冗余操作人用户名、分页、meta。"""
import time

from tests.conftest import PW, issue_body

A = "/admin/api"


def _issue(client, h, **kw):
    r = client.post(f"{A}/licenses", json=issue_body(**kw), headers=h)
    assert r.status_code == 201, r.text
    return r.json()["license"]


def test_audit_has_admin_username(client, root, ops):
    lic = _issue(client, ops)
    items = client.get(f"{A}/audit?page_size=100", headers=root).json()["items"]
    issue_row = next(i for i in items if i["action"] == "license.issue")
    assert issue_row["admin_username"] == "oper"
    login_row = next(i for i in items if i["action"] == "auth.login_success")
    assert login_row["admin_username"] in ("root", "oper")
    assert all("admin_username" in i for i in items)


def test_legacy_audit_without_username_returns_null(client, repos, root):
    client.portal.call(repos.audit.insert, {"admin_id": "legacy-admin-id", "action": "x.old", "target": "t",
                                            "before": None, "after": None, "ip": "", "at": 1, "seq": 1})
    items = client.get(f"{A}/audit?action=x.old", headers=root).json()["items"]
    assert items[0]["admin_username"] is None and items[0]["admin_id"] == "legacy-admin-id"


def test_license_created_by_username_and_event_actor(client, ops, root):
    lic = _issue(client, ops)
    assert lic["created_by_username"] == "oper"
    got = client.get(f"{A}/licenses/{lic['lid']}", headers=root).json()
    assert got["created_by_username"] == "oper"
    ev = client.get(f"{A}/licenses/{lic['lid']}/events", headers=root).json()["items"]
    assert ev[0]["type"] == "issued" and ev[0]["actor_username"] == "oper"


def test_legacy_license_and_event_null_username(client, repos, root):
    lic = _issue(client, root)
    lid = lic["lid"]
    # 模拟历史记录：没有 *_username 字段
    client.portal.call(repos.events.insert, {"lid": lid, "type": "old", "detail": {}, "ip": "", "admin_id": "x",
                                             "at": int(time.time()) + 1, "seq": time.time_ns()})
    evs = client.get(f"{A}/licenses/{lid}/events?order=asc", headers=root).json()["items"]
    assert evs[-1]["type"] == "old" and evs[-1]["actor_username"] is None


def test_events_pagination_default_desc(client, root, repos):
    lid = _issue(client, root)["lid"]
    for i in range(5):
        client.portal.call(repos.events.insert, {"lid": lid, "type": f"e{i}", "detail": {}, "ip": "",
                                                 "admin_id": None, "at": int(time.time()) + i + 1,
                                                 "seq": time.time_ns()})
    r = client.get(f"{A}/licenses/{lid}/events?page_size=2", headers=root).json()
    assert r["total"] == 6 and r["page"] == 1 and r["page_size"] == 2
    assert [e["type"] for e in r["items"]] == ["e4", "e3"]
    r2 = client.get(f"{A}/licenses/{lid}/events?page_size=2&page=3", headers=root).json()
    assert [e["type"] for e in r2["items"]] == ["e0", "issued"] or [e["type"] for e in r2["items"]] == ["issued"]
    assert client.get(f"{A}/licenses/{lid}/events?page_size=101", headers=root).status_code == 422
    assert client.get(f"{A}/licenses/{lid}/events?order=bad", headers=root).status_code == 422
    # 默认值向后兼容：不带参数返回全部（<=100）
    assert len(client.get(f"{A}/licenses/{lid}/events", headers=root).json()["items"]) == 6


def test_admins_pagination(client, root):
    for i in range(4):
        assert client.post(f"{A}/admins", headers=root,
                           json={"username": f"extra{i}", "password": PW, "role": "readonly"}).status_code == 201
    r = client.get(f"{A}/admins?page_size=2&page=2", headers=root).json()
    assert r["total"] == 5 and r["page"] == 2 and r["page_size"] == 2 and len(r["items"]) == 2
    assert "password_hash" not in str(r)
    assert len(client.get(f"{A}/admins", headers=root).json()["items"]) == 5
    assert client.get(f"{A}/admins?page_size=0", headers=root).status_code == 422


def test_meta(client, root, ops, ro, settings):
    for h in (root, ops, ro):
        m = client.get(f"{A}/meta", headers=h).json()
        assert m["plans"] == list(settings.plans)
        assert m["features"]["pattern"] == "^[a-z0-9_]{1,40}$" and m["features"]["max_length"] == 40
        assert m["machine_code"]["min_components"] == 2
    assert client.get(f"{A}/meta").status_code == 401
