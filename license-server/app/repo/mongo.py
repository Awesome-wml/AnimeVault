"""Mongo 仓库（motor）。audit_logs 只提供 insert / search。"""
from __future__ import annotations

import re
import time
from typing import Any, Dict, List, Optional, Tuple

from pymongo import ASCENDING, DESCENDING
from pymongo.errors import DuplicateKeyError

from .base import (AdminRepo, AuditRepo, DeviceRepo, DuplicateError, EventRepo, KeyRepo,
                   LeaseRepo, LicenseRepo, Repos, RequestRepo)

_P = {"_id": 0}


def _ci(text: str) -> Dict[str, Any]:
    return {"$regex": re.escape(text), "$options": "i"}


class MongoLicenses(LicenseRepo):
    def __init__(self, col):
        self.c = col

    async def insert(self, doc):
        try:
            await self.c.insert_one(dict(doc))
        except DuplicateKeyError:
            raise DuplicateError("lid") from None
        return doc

    async def get(self, lid):
        return await self.c.find_one({"lid": lid}, _P)

    async def update(self, lid, fields, expect_status=None):
        flt: Dict[str, Any] = {"lid": lid}
        if expect_status is not None:
            flt["status"] = {"$in": list(expect_status)}
        from pymongo import ReturnDocument
        return await self.c.find_one_and_update(flt, {"$set": fields}, projection=_P,
                                                return_document=ReturnDocument.AFTER)

    async def search(self, *, status=None, email=None, lid=None, skip=0, limit=20):
        flt: Dict[str, Any] = {}
        if status:
            flt["status"] = status
        if email:
            flt["$or"] = [{"email": _ci(email)}, {"uid": _ci(email)}]
        if lid:
            flt["lid"] = _ci(lid)
        total = await self.c.count_documents(flt)
        cur = self.c.find(flt, _P).sort([("issued_at", DESCENDING), ("lid", DESCENDING)]).skip(skip).limit(limit)
        return [d async for d in cur], total

    async def find_same_machine(self, components):
        cur = self.c.find({"machine_components": {"$all": components, "$size": len(set(components))},
                           "status": {"$ne": "revoked"}}, _P)
        return [d async for d in cur]

    async def list_due(self, now):
        return [d async for d in self.c.find({"status": "active", "expires_at": {"$lte": now}}, _P)]


class MongoAdmins(AdminRepo):
    def __init__(self, col):
        self.c = col

    async def insert(self, doc):
        try:
            await self.c.insert_one(dict(doc))
        except DuplicateKeyError:
            raise DuplicateError("username") from None
        return doc

    async def get(self, admin_id):
        return await self.c.find_one({"id": admin_id}, _P)

    async def get_by_username(self, username):
        return await self.c.find_one({"username": username}, _P)

    async def update(self, admin_id, fields):
        from pymongo import ReturnDocument
        return await self.c.find_one_and_update({"id": admin_id}, {"$set": fields}, projection=_P,
                                                return_document=ReturnDocument.AFTER)

    async def list(self):
        return [d async for d in self.c.find({}, _P).sort("created_at", ASCENDING)]

    async def page(self, skip=0, limit=100):
        total = await self.c.count_documents({})
        cur = self.c.find({}, _P).sort("created_at", ASCENDING).skip(skip).limit(limit)
        return [d async for d in cur], total

    async def count_enabled_super(self):
        return await self.c.count_documents({"role": "super", "enabled": True})


class MongoAudit(AuditRepo):
    """刻意不提供 update / delete。"""

    def __init__(self, col):
        self.c = col

    async def insert(self, doc):
        await self.c.insert_one(dict(doc))

    async def search(self, *, action=None, admin_id=None, skip=0, limit=20):
        flt: Dict[str, Any] = {}
        if action:
            flt["action"] = action
        if admin_id:
            flt["admin_id"] = admin_id
        total = await self.c.count_documents(flt)
        cur = self.c.find(flt, _P).sort([("at", DESCENDING), ("seq", DESCENDING)]).skip(skip).limit(limit)
        return [d async for d in cur], total


class MongoEvents(EventRepo):
    def __init__(self, col):
        self.c = col

    async def insert(self, doc):
        await self.c.insert_one(dict(doc))

    async def list_for(self, lid):
        return [d async for d in self.c.find({"lid": lid}, _P).sort([("at", ASCENDING), ("seq", ASCENDING)])]

    async def search(self, lid, *, skip=0, limit=100, desc=True):
        d = DESCENDING if desc else ASCENDING
        total = await self.c.count_documents({"lid": lid})
        cur = self.c.find({"lid": lid}, _P).sort([("at", d), ("seq", d)]).skip(skip).limit(limit)
        return [x async for x in cur], total


class MongoKeys(KeyRepo):
    def __init__(self, col):
        self.c = col

    async def upsert(self, kid, public_key, status="active"):
        await self.c.update_one({"kid": kid}, {
            "$set": {"public_key": public_key, "status": status},
            "$setOnInsert": {"created_at": int(time.time())}}, upsert=True)

    async def list(self):
        return [d async for d in self.c.find({}, _P)]


class MongoDevices(DeviceRepo):
    def __init__(self, col):
        self.c = col

    async def insert(self, doc):
        await self.c.insert_one(dict(doc))

    async def list_for(self, lid):
        return [d async for d in self.c.find({"lid": lid}, _P).sort("first_seen_at", ASCENDING)]

    async def update(self, lid, did, fields):
        from pymongo import ReturnDocument
        return await self.c.find_one_and_update({"lid": lid, "did": did}, {"$set": fields}, projection=_P,
                                                return_document=ReturnDocument.AFTER)


class MongoLeases(LeaseRepo):
    def __init__(self, col):
        self.c = col

    async def upsert(self, lid, sid, fields):
        # 同一路径不能同时出现在 $set 与 $setOnInsert（Mongo 报 conflict）：fields 里已有 revoked 时不再设默认值
        on_insert: Dict[str, Any] = {"lid": lid, "sid": sid}
        if "revoked" not in fields:
            on_insert["revoked"] = False
        await self.c.update_one({"lid": lid, "sid": sid}, {"$set": fields, "$setOnInsert": on_insert},
                                upsert=True)

    async def get(self, lid, sid):
        return await self.c.find_one({"lid": lid, "sid": sid}, _P)

    async def list_for(self, lid):
        return [d async for d in self.c.find({"lid": lid}, _P)]

    async def revoke_others(self, lid, keep_sid):
        r = await self.c.update_many({"lid": lid, "sid": {"$ne": keep_sid}, "revoked": {"$ne": True}},
                                     {"$set": {"revoked": True}})
        return r.modified_count


class MongoRequests(RequestRepo):
    def __init__(self, col):
        self.c = col

    async def insert(self, doc):
        try:
            await self.c.insert_one(dict(doc))
        except DuplicateKeyError:
            raise DuplicateError("dedup_key") from None
        return doc

    async def get(self, rid):
        return await self.c.find_one({"id": rid}, _P)

    async def update(self, rid, fields, expect_status=None):
        from pymongo import ReturnDocument
        flt: Dict[str, Any] = {"id": rid}
        if expect_status is not None:
            flt["status"] = {"$in": list(expect_status)}
        return await self.c.find_one_and_update(flt, {"$set": fields}, projection=_P,
                                                return_document=ReturnDocument.AFTER)

    async def search(self, *, status=None, skip=0, limit=20):
        flt: Dict[str, Any] = {"status": status} if status else {}
        total = await self.c.count_documents(flt)
        cur = self.c.find(flt, _P).sort([("created_at", DESCENDING), ("seq", DESCENDING)]).skip(skip).limit(limit)
        return [d async for d in cur], total


class MongoRepos(Repos):
    def __init__(self, client, db_name: str):
        db = client[db_name]
        self._client, self._db = client, db
        super().__init__(MongoLicenses(db["licenses"]), MongoAdmins(db["admins"]),
                         MongoAudit(db["audit_logs"]), MongoEvents(db["license_events"]),
                         MongoKeys(db["keys"]), MongoDevices(db["devices"]), MongoLeases(db["leases"]),
                         MongoRequests(db["activation_reqs"]))

    async def ensure_ready(self):
        db = self._db
        await db["licenses"].create_index("lid", unique=True)
        await db["licenses"].create_index("uid")
        await db["licenses"].create_index("status")
        await db["admins"].create_index("username", unique=True)
        await db["admins"].create_index("id", unique=True)
        await db["license_events"].create_index([("lid", ASCENDING), ("at", ASCENDING)])
        await db["devices"].create_index("lid")
        await db["leases"].create_index([("lid", ASCENDING), ("sid", ASCENDING)], unique=True)
        await db["audit_logs"].create_index("at")
        await db["activation_reqs"].create_index("id", unique=True)
        await db["activation_reqs"].create_index([("status", ASCENDING), ("created_at", DESCENDING)])
        # 同邮箱+同机器码未处理的申请只能有一条（部分唯一索引，已处理的不受限）
        await db["activation_reqs"].create_index("dedup_key", unique=True,
                                                 partialFilterExpression={"status": "pending"})
        await db["keys"].create_index("kid", unique=True)

    async def close(self):
        self._client.close()


def make_mongo_repos(url: str, db_name: str) -> MongoRepos:
    from motor.motor_asyncio import AsyncIOMotorClient
    return MongoRepos(AsyncIOMotorClient(url, serverSelectionTimeoutMS=5000), db_name)
