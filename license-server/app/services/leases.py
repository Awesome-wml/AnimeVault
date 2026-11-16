"""租约：签发、续租、状态查询（设计 6、9.1）。

安全约定：授权码和租约原文不进日志、不进事件；日志里只出现 lid 和 sid 前 6 位。
续租不校验授权码（授权码被延期重签后，已有租约仍可续租），只校验状态、到期、会话。
"""
from __future__ import annotations

import logging
import secrets
import time
from typing import Any, Dict, List, Optional

from dongai_license import license_token as lt

from ..config import Settings
from ..errors import ApiError
from ..repo.base import Repos
from .audit import Actor
from .licenses import ACTIVE, EXPIRED, PENDING, REVOKED, SUSPENDED, LicenseService
from .ratelimit import RateLimiter

log = logging.getLogger("license.client")

RENEW_EVENT_INTERVAL = 3600  # 续租成功事件最多每小时写一次


def sid6(sid: Optional[str]) -> str:
    return (sid or "")[:6]


def e_invalid(message: str = "授权无效") -> ApiError:
    return ApiError(401, "LICENSE_INVALID", message)


def e_mismatch() -> ApiError:
    return ApiError(403, "LICENSE_MACHINE_MISMATCH", "授权与本机不匹配")


def e_expired() -> ApiError:
    return ApiError(403, "LICENSE_EXPIRED", "授权已到期")


def e_lease_expired() -> ApiError:
    return ApiError(401, "LEASE_EXPIRED", "租约已过期，请重新激活")


def e_conflict() -> ApiError:
    return ApiError(409, "LICENSE_SESSION_CONFLICT", "该授权已在其他会话中使用")


class LeaseService:
    def __init__(self, repos: Repos, settings: Settings, licenses: LicenseService,
                 limiter: Optional[RateLimiter] = None, clock=time.time):
        self.r, self.s, self.licenses, self.clock = repos, settings, licenses, clock
        self.limiter = limiter or RateLimiter(clock)

    def now(self) -> int:
        return int(self.clock())

    def public_keys(self) -> Dict[str, str]:
        return {self.s.signing_kid: self.s.signing_public_key}

    async def event(self, lid: str, type_: str, ip: str, detail: Optional[dict] = None) -> None:
        await self.r.events.insert({"lid": lid, "type": type_, "detail": detail or {}, "ip": ip,
                                    "admin_id": None, "actor_username": None, "at": self.now(), "seq": time.time_ns()})

    # ---------- 状态判定 ----------
    async def check_status(self, lic: Dict[str, Any]) -> None:
        """可用（active，且未到期）则返回，否则抛对应错误。pending 视为不可续租，激活流程自行处理。"""
        st = lic["status"]
        if st == REVOKED:
            raise ApiError(403, "LICENSE_REVOKED", "授权已被吊销")
        if st == SUSPENDED:
            raise ApiError(403, "LICENSE_SUSPENDED", "授权已被停用")
        if st == EXPIRED or int(lic["expires_at"]) <= self.now():
            if st == ACTIVE:
                await self.licenses.expire_due()
            raise e_expired()
        if st != ACTIVE:
            raise e_invalid()

    def lease_ttl(self, lic: Dict[str, Any]) -> int:
        """租约有效期：默认 ttl，且不超过授权到期时间。
        租约另外携带已签名的 lexp/plan/features/cv（取自授权记录），客户端据此区分「租约过期」与「授权到期」。"""
        ttl = min(self.s.lease_ttl_seconds, int(lic["expires_at"]) - self.now())
        if ttl <= 0:
            raise e_expired()
        return ttl

    def sign_lease(self, lic: Dict[str, Any], sid: str, mc: List[str]) -> tuple:
        ttl = self.lease_ttl(lic)
        now = self.now()
        token = lt.issue_lease(self.s.signing_private_key, self.s.signing_kid, lid=lic["lid"], mc=mc,
                               sid=sid, ttl_seconds=ttl, st=ACTIVE, iat=now,
                               lexp=int(lic["expires_at"]), plan=lic["plan"],
                               features=list(lic["features"]), cv=int(lic.get("code_version", 1)))
        return token, now + ttl

    @staticmethod
    def license_view(lic: Dict[str, Any], status: Optional[str] = None) -> Dict[str, Any]:
        """响应 JSON 里的 license 视图：仅展示，不在签名内，不可信；决策以租约内签名字段为准。"""
        return {"plan": lic["plan"], "features": lic["features"], "expires_at": lic["expires_at"],
                "status": status or lic["status"]}

    # ---------- 租约验证 ----------
    def open_lease(self, lease: str, comps: List[str]) -> Dict[str, Any]:
        """验签 + 机器码匹配；已过期的租约在宽限期内仍返回 payload，超出宽限抛 LEASE_EXPIRED。"""
        now = self.now()
        try:
            return lt.verify_lease(lease, self.public_keys(), comps, now=now)
        except lt.LeaseExpired as e:
            if now >= e.payload["exp"] + self.s.renew_grace_seconds:
                raise e_lease_expired() from None
            return e.payload
        except lt.MachineMismatch:
            raise e_mismatch() from None
        except lt.LicenseError:
            raise e_invalid() from None

    async def _load(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        lic = await self.r.licenses.get(payload["lid"])
        if lic is None:
            raise e_invalid()
        return lic

    # ---------- 续租 ----------
    async def renew(self, lease: str, comps: List[str], app_version: str, ip: str) -> Dict[str, Any]:
        payload = self.open_lease(lease, comps)
        lid, sid = payload["lid"], payload["sid"]
        lic = await self._load(payload)
        await self.check_status(lic)
        if lic.get("active_sid") != sid:  # 单会话：后一次激活获胜
            log.info("renew conflict lid=%s sid=%s", lid, sid6(sid))
            raise e_conflict()
        now = self.now()
        token, exp = self.sign_lease(lic, sid, comps)
        prev_event = lic.get("last_renew_event_at")
        write_event = prev_event is None or now - int(prev_event) >= RENEW_EVENT_INTERVAL
        fields = {"last_seen_at": now, "last_seen_ip": ip, "last_renew_at": now}
        if write_event:
            fields["last_renew_event_at"] = now
        new = await self.r.licenses.update(lid, fields, expect_status=(ACTIVE,))
        if new is None:  # 并发下状态刚被改：按最新状态返回错误
            await self.check_status(await self._load(payload))
            raise e_invalid()
        if new.get("active_sid") != sid:  # 刚好被新会话顶掉
            raise e_conflict()
        await self.r.leases.upsert(lid, sid, {"mc": list(comps), "expires_at": exp, "ip": ip,
                                              "issued_at": now, "revoked": False})
        await self.touch_device(lid, comps, ip, app_version, now)
        if write_event:
            await self.event(lid, "renewed", ip, {"sid": sid6(sid), "app_version": app_version[:32]})
        log.info("renew ok lid=%s sid=%s", lid, sid6(sid))
        return {"lease": token, "expires_at": exp, "server_time": now, "license": self.license_view(new)}

    async def touch_device(self, lid: str, comps: List[str], ip: str, app_version: str, now: int) -> None:
        for d in await self.r.devices.list_for(lid):
            if d.get("bound", True) and lt.components_match(d["mc"], comps):
                await self.r.devices.update(lid, d["did"], {
                    "mc": list(comps), "last_seen_at": now, "last_ip": ip, "app_version": app_version[:32]})
                return

    # ---------- 状态 ----------
    async def status(self, lease: str, comps: List[str]) -> Dict[str, Any]:
        payload = self.open_lease(lease, comps)
        lic = await self._load(payload)
        st = lic["status"]
        if st == ACTIVE and int(lic["expires_at"]) <= self.now():
            st = EXPIRED
        return {"status": st, **self.license_view(lic, st),
                "session_active": lic.get("active_sid") == payload["sid"],
                "lease_expires_at": payload["exp"], "server_time": self.now()}


def new_sid() -> str:
    return secrets.token_urlsafe(16)
