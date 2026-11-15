"""内存仓库：测试和本地演示用，进程退出即丢失。"""
from __future__ import annotations

import copy
import time
from typing import Any, Dict, List, Optional, Tuple

from .base import (AdminRepo, AuditRepo, DeviceRepo, DuplicateError, EventRepo, KeyRepo,
                   LeaseRepo, LicenseRepo, Repos)


def _c(d):
    return copy.deepcopy(d) if d is not None else None


class MemLicenses(LicenseRepo):
    def __init__(self):
        self._d: Dict[str, Dict[str, Any]] = {}

    async def insert(self, doc):
        if doc["lid"] in self._d:
            raise DuplicateError("lid")
        self._d[doc["lid"]] = _c(doc)
        return _c(doc)

    async def get(self, lid):
        return _c(self._d.get(lid))

    async def update(self, lid, fields, expect_status=None):
        cur = self._d.get(lid)
        if cur is None or (expect_status is not None and cur["status"] not in expect_status):
            return None
        cur.update(_c(fields))
        return _c(cur)

    async def search(self, *, status=None, email=None, lid=None, skip=0, limit=20):
        rows = list(self._d.values())
        if status:
            rows = [r for r in rows if r["status"] == status]
        if email:
            rows = [r for r in rows if email.lower() in (r.get("email") or "").lower()
                    or email.lower() in (r.get("uid") or "").lower()]
        if lid:
            rows = [r for r in rows if lid.lower() in r["lid"].lower()]
        rows.sort(key=lambda r: (r["issued_at"], r["lid"]), reverse=True)
        return [_c(r) for r in rows[skip:skip + limit]], len(rows)

    async def find_same_machine(self, components):
        s = set(components)
        return [_c(r) for r in self._d.values()
                if set(r["machine_components"]) == s and r["status"] != "revoked"]

    async def list_due(self, now):
        return [_c(r) for r in self._d.values() if r["status"] == "active" and r["expires_at"] <= now]


class MemAdmins(AdminRepo):
    def __init__(self):
        self._d: Dict[str, Dict[str, Any]] = {}

    async def insert(self, doc):
        if any(a["username"] == doc["username"] for a in self._d.values()):
            raise DuplicateError("username")
        self._d[doc["id"]] = _c(doc)
        return _c(doc)

    async def get(self, admin_id):
        return _c(self._d.get(admin_id))

    async def get_by_username(self, username):
        for a in self._d.values():
            if a["username"] == username:
                return _c(a)
        return None

    async def update(self, admin_id, fields):
        cur = self._d.get(admin_id)
        if cur is None:
            return None
        cur.update(_c(fields))
        return _c(cur)

    async def list(self):
        return [_c(a) for a in sorted(self._d.values(), key=lambda a: a["created_at"])]

    async def page(self, skip=0, limit=100):
        rows = await self.list()
        return rows[skip:skip + limit], len(rows)

    async def count_enabled_super(self):
        return sum(1 for a in self._d.values() if a["role"] == "super" and a["enabled"])


class MemAudit(AuditRepo):
    def __init__(self):
        self._d: List[Dict[str, Any]] = []

    async def insert(self, doc):
        self._d.append(_c(doc))

    async def search(self, *, action=None, admin_id=None, skip=0, limit=20):
        rows = [r for r in self._d
                if (not action or r["action"] == action) and (not admin_id or r["admin_id"] == admin_id)]
        rows = rows[::-1]  # 最新在前（插入顺序反转，同秒也稳定）
        return [_c(r) for r in rows[skip:skip + limit]], len(rows)


class MemEvents(EventRepo):
    def __init__(self):
        self._d: List[Dict[str, Any]] = []

    async def insert(self, doc):
        self._d.append(_c(doc))

    async def list_for(self, lid):
        return [_c(r) for r in self._d if r["lid"] == lid]

    async def search(self, lid, *, skip=0, limit=100, desc=True):
        rows = sorted((r for r in self._d if r["lid"] == lid), key=lambda r: (r["at"], r.get("seq", 0)),
                      reverse=desc)
        return [_c(r) for r in rows[skip:skip + limit]], len(rows)


class MemKeys(KeyRepo):
    def __init__(self):
        self._d: Dict[str, Dict[str, Any]] = {}

    async def upsert(self, kid, public_key, status="active"):
        cur = self._d.get(kid)
        self._d[kid] = {"kid": kid, "public_key": public_key, "status": status,
                        "created_at": cur["created_at"] if cur else int(time.time())}

    async def list(self):
        return [_c(v) for v in self._d.values()]


class MemDevices(DeviceRepo):
    def __init__(self):
        self._d: List[Dict[str, Any]] = []

    async def insert(self, doc):
        self._d.append(_c(doc))

    async def list_for(self, lid):
        return [_c(r) for r in sorted((r for r in self._d if r["lid"] == lid),
                                      key=lambda r: r["first_seen_at"])]

    async def update(self, lid, did, fields):
        for r in self._d:
            if r["lid"] == lid and r["did"] == did:
                r.update(_c(fields))
                return _c(r)
        return None


class MemLeases(LeaseRepo):
    def __init__(self):
        self._d: Dict[tuple, Dict[str, Any]] = {}

    async def upsert(self, lid, sid, fields):
        cur = self._d.setdefault((lid, sid), {"lid": lid, "sid": sid, "revoked": False})
        cur.update(_c(fields))

    async def get(self, lid, sid):
        return _c(self._d.get((lid, sid)))

    async def list_for(self, lid):
        return [_c(r) for (l, _), r in self._d.items() if l == lid]

    async def revoke_others(self, lid, keep_sid):
        n = 0
        for (l, s), r in self._d.items():
            if l == lid and s != keep_sid and not r.get("revoked"):
                r["revoked"] = True
                n += 1
        return n


def make_memory_repos() -> Repos:
    return Repos(MemLicenses(), MemAdmins(), MemAudit(), MemEvents(), MemKeys(), MemDevices(), MemLeases())
