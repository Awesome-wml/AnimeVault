"""申请单（设计第 8、9 节 activation_reqs）：客户端提交机器码和邮箱，管理员审核后签发或驳回。"""
from __future__ import annotations

import re
import secrets
import time
from typing import Any, Dict, List, Optional

from dongai_license.machine_code import parse_machine_code

from ..config import Settings
from ..errors import ApiError
from ..repo.base import DuplicateError, Repos
from .audit import Actor, AuditService
from .licenses import LicenseService
from .ratelimit import RateLimiter

REQUEST_IP_LIMIT = 5        # 每 IP 每小时
REQUEST_WINDOW = 3600
STATUSES = ("pending", "issued", "rejected")
_EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[^@\s.]{2,}$")


def request_view(r: Dict[str, Any]) -> Dict[str, Any]:
    out = {k: r.get(k) for k in ("id", "email", "machine_code", "note", "status", "created_at", "ip",
                                 "handled_by", "handled_by_username", "handled_at", "lid", "reason")}
    out["components_count"] = len(r.get("mc") or [])
    return out


class RequestService:
    def __init__(self, repos: Repos, settings: Settings, licenses: LicenseService, audit: AuditService,
                 clock=time.time):
        self.r, self.s, self.licenses, self.audit, self.clock = repos, settings, licenses, audit, clock
        self.limiter = RateLimiter(clock, window=REQUEST_WINDOW)

    def now(self) -> int:
        return int(self.clock())

    # ---------- 客户端提交 ----------
    async def submit(self, email: str, machine_code: str, note: Optional[str], ip: str) -> Dict[str, Any]:
        self.limiter.hit(f"req-ip:{ip}", REQUEST_IP_LIMIT)
        email = (email or "").strip().lower()
        if not _EMAIL_RE.match(email):
            raise ApiError(422, "EMAIL_INVALID", "邮箱格式不正确")
        try:
            comps = parse_machine_code(machine_code)
        except ValueError as e:
            raise ApiError(422, "MACHINE_CODE_INVALID", str(e)) from None
        if len(comps) < 2:
            raise ApiError(422, "MACHINE_CODE_TOO_FEW", "机器码分量不足 2 个，无法提交")
        doc = {"id": "req_" + secrets.token_hex(8), "email": email, "machine_code": machine_code.strip(),
               "mc": comps, "dedup_key": email + "|" + ",".join(sorted(comps)), "note": (note or "").strip() or None,
               "status": "pending", "created_at": self.now(), "seq": time.time_ns(), "ip": ip,
               "handled_by": None, "handled_by_username": None, "handled_at": None, "lid": None, "reason": None}
        try:
            await self.r.requests.insert(doc)
        except DuplicateError:
            pass  # 同邮箱+同机器码已有未处理申请：幂等，不重复建单，也不向客户端泄露内部信息
        return {"status": "pending"}

    # ---------- 管理端 ----------
    async def list(self, status: Optional[str], page: int, page_size: int):
        if status and status not in STATUSES:
            raise ApiError(422, "STATUS_INVALID", "状态只能是 pending / issued / rejected")
        items, total = await self.r.requests.search(status=status, skip=(page - 1) * page_size, limit=page_size)
        return [request_view(i) for i in items], total

    async def _get(self, rid: str) -> Dict[str, Any]:
        req = await self.r.requests.get(rid)
        if req is None:
            raise ApiError(404, "REQUEST_NOT_FOUND", "申请单不存在")
        return req

    @staticmethod
    def _not_pending(req: Dict[str, Any]) -> ApiError:
        return ApiError(409, "REQUEST_NOT_PENDING", f"申请单当前状态为 {req['status']}，不能再处理",
                        {"status": req["status"]})

    async def reject(self, actor: Actor, rid: str, reason: Optional[str]) -> Dict[str, Any]:
        req = await self._get(rid)
        new = await self.r.requests.update(rid, {
            "status": "rejected", "handled_by": actor.admin_id, "handled_by_username": actor.username,
            "handled_at": self.now(), "reason": (reason or "").strip() or None}, expect_status=("pending",))
        if new is None:
            raise self._not_pending(await self._get(rid))
        await self.audit.record(actor, "request.reject", f"request:{rid}",
                                {"status": req["status"]}, {"status": "rejected", "reason": new["reason"]})
        return request_view(new)

    async def issue(self, actor: Actor, rid: str, *, plan: str, features: List[str], expires_at: int,
                    dev_max: int, note: Optional[str]) -> Dict[str, Any]:
        """先把申请单从 pending 原子占为 issued（并发只有一个管理员成功），再调用现有签发服务（复用全部校验）；
        签发失败则回滚为 pending。"""
        req = await self._get(rid)
        claimed = await self.r.requests.update(rid, {
            "status": "issued", "handled_by": actor.admin_id, "handled_by_username": actor.username,
            "handled_at": self.now()}, expect_status=("pending",))
        if claimed is None:
            raise self._not_pending(await self._get(rid))
        try:
            res = await self.licenses.issue(
                actor, machine_code=req["machine_code"], plan=plan, features=features, expires_at=expires_at,
                uid=None, email=req["email"], dev_max=dev_max, note=note or req.get("note"))
        except BaseException:
            await self.r.requests.update(rid, {"status": "pending", "handled_by": None, "handled_by_username": None,
                                               "handled_at": None}, expect_status=("issued",))
            raise
        lid = res["license"]["lid"]
        new = await self.r.requests.update(rid, {"lid": lid})
        await self.audit.record(actor, "request.issue", f"request:{rid}",
                                {"status": "pending"}, {"status": "issued", "lid": lid})
        return {"request": request_view(new), **res}
