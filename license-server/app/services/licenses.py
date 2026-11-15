"""授权服务：签发、延期、状态机。状态机见设计 7.3。"""
from __future__ import annotations

import hashlib
import re
import secrets
import time
from typing import Any, Dict, List, Optional

from dongai_license import license_token as lt
from dongai_license.machine_code import parse_machine_code

from ..config import Settings
from ..errors import ApiError
from ..repo.base import DuplicateError, Repos
from .audit import Actor, AuditService

PENDING, ACTIVE, SUSPENDED, REVOKED, EXPIRED = "pending", "active", "suspended", "revoked", "expired"
FEATURE_PATTERN = "^[a-z0-9_]{1,40}$"
_FEATURE_RE = re.compile(FEATURE_PATTERN)


def _state_error(lic: Dict[str, Any], action: str) -> ApiError:
    return ApiError(409, "INVALID_TRANSITION",
                    f"授权当前状态为 {lic['status']}，不能执行 {action}",
                    {"status": lic["status"], "action": action})


def _fingerprint(code: Optional[str]) -> Optional[str]:
    return hashlib.sha256(code.encode()).hexdigest()[:12] if code else None


class LicenseService:
    def __init__(self, repos: Repos, settings: Settings, audit: AuditService, clock=time.time):
        self.r, self.s, self.audit, self.clock = repos, settings, audit, clock

    def now(self) -> int:
        return int(self.clock())

    # ---------- 内部工具 ----------
    def _sign(self, lic: Dict[str, Any]) -> str:
        return lt.issue_license(
            self.s.signing_private_key, self.s.signing_kid, lid=lic["lid"],
            mc=lic["machine_components"], plan=lic["plan"], features=lic["features"],
            exp=lic["expires_at"], uid=lic.get("uid"), dev_max=lic["dev_max"], iat=self.now())

    async def _event(self, lid: str, type_: str, actor: Actor, detail: Optional[dict] = None) -> None:
        await self.r.events.insert({"lid": lid, "type": type_, "detail": detail or {}, "ip": actor.ip,
                                    "admin_id": actor.admin_id, "actor_username": actor.username,
                                    "at": self.now(), "seq": time.time_ns()})

    def _future(self, exp: int) -> None:
        if exp <= self.now():
            raise ApiError(422, "EXPIRES_IN_PAST", "到期时间必须在未来")

    @staticmethod
    def snapshot(lic: Dict[str, Any]) -> Dict[str, Any]:
        """用于审计的快照：不含授权码。"""
        return {k: v for k, v in lic.items() if k != "code"}

    async def _transition(self, lid: str, action: str, actor: Actor, *, allowed, to: str,
                          extra: Optional[dict] = None, event: str) -> Dict[str, Any]:
        lic = await self._get_fresh(lid)
        if lic["status"] not in allowed:
            raise _state_error(lic, action)
        fields = {"status": to, **(extra or {})}
        new = await self.r.licenses.update(lid, fields, expect_status=tuple(allowed))
        if new is None:  # 并发下被别人改了状态
            raise _state_error(await self._get_fresh(lid), action)
        await self._event(lid, event, actor, {"from": lic["status"], "to": to})
        await self.audit.record(actor, f"license.{action}", f"license:{lid}",
                                self.snapshot(lic), self.snapshot(new))
        return new

    async def _get_fresh(self, lid: str) -> Dict[str, Any]:
        await self.expire_due()
        lic = await self.r.licenses.get(lid)
        if lic is None:
            raise ApiError(404, "LICENSE_NOT_FOUND", "授权不存在")
        return lic

    # ---------- 查询 ----------
    async def get(self, lid: str) -> Dict[str, Any]:
        return await self._get_fresh(lid)

    async def list(self, *, status, email, lid, page: int, page_size: int):
        await self.expire_due()  # 惰性到期
        items, total = await self.r.licenses.search(status=status, email=email, lid=lid,
                                                    skip=(page - 1) * page_size, limit=page_size)
        return items, total

    async def events(self, lid: str, *, page: int = 1, page_size: int = 100, desc: bool = True):
        await self._get_fresh(lid)
        return await self.r.events.search(lid, skip=(page - 1) * page_size, limit=page_size, desc=desc)

    # ---------- 签发 ----------
    async def issue(self, actor: Actor, *, machine_code: str, plan: str, features: List[str],
                    expires_at: int, uid: Optional[str], email: Optional[str], dev_max: int,
                    note: Optional[str]) -> Dict[str, Any]:
        try:
            comps = parse_machine_code(machine_code)
        except ValueError as e:
            raise ApiError(422, "MACHINE_CODE_INVALID", str(e)) from None
        if len(comps) < 2:
            raise ApiError(422, "MACHINE_CODE_TOO_FEW", "机器码分量不足 2 个，拒绝签发（防止误绑）")
        if plan not in self.s.plans:
            raise ApiError(422, "PLAN_INVALID", f"套餐无效，可选：{', '.join(self.s.plans)}")
        bad = [f for f in features if not _FEATURE_RE.match(f)]
        if bad:
            raise ApiError(422, "FEATURE_INVALID", "功能标识只能是小写字母、数字、下划线")
        self._future(expires_at)
        same = await self.r.licenses.find_same_machine(comps)

        now = self.now()
        lic = {
            "lid": "lic_" + secrets.token_hex(8), "uid": uid or None, "email": email or None,
            "plan": plan, "features": sorted(set(features)), "dev_max": dev_max, "status": PENDING,
            "issued_at": now, "expires_at": expires_at, "activated_at": None, "note": note,
            "created_by": actor.admin_id, "created_by_username": actor.username,
            "machine_components": comps, "code": None,
            "code_version": 1, "last_seen_at": None,
            "active_sid": None, "last_seen_ip": None, "last_renew_at": None,
        }
        lic["code"] = self._sign(lic)
        try:
            await self.r.licenses.insert(lic)
        except DuplicateError:  # lid 碰撞概率可忽略，出现就让调用方重试
            raise ApiError(500, "LID_COLLISION", "授权 ID 冲突，请重试") from None
        await self._event(lic["lid"], "issued", actor, {"plan": plan, "expires_at": expires_at,
                                                         "code_fp": _fingerprint(lic["code"])})
        await self.audit.record(actor, "license.issue", f"license:{lic['lid']}", None, self.snapshot(lic))
        warnings = []
        if same:
            warnings.append(f"该机器码已有 {len(same)} 条未吊销授权（{', '.join(x['lid'] for x in same)}），请确认不是重复签发")
        return {"license": lic, "same_machine_count": len(same), "warnings": warnings}

    # ---------- 状态变更 ----------
    async def extend(self, actor: Actor, lid: str, expires_at: int) -> Dict[str, Any]:
        self._future(expires_at)
        lic = await self._get_fresh(lid)
        if lic["status"] == REVOKED:
            raise _state_error(lic, "extend")
        draft = dict(lic, expires_at=expires_at)
        code = self._sign(draft)
        to = ACTIVE if lic["status"] == EXPIRED else lic["status"]
        new = await self.r.licenses.update(
            lid, {"expires_at": expires_at, "code": code, "code_version": lic["code_version"] + 1, "status": to},
            expect_status=(PENDING, ACTIVE, SUSPENDED, EXPIRED))
        if new is None:
            raise _state_error(await self._get_fresh(lid), "extend")
        await self._event(lid, "extended", actor, {
            "old_expires_at": lic["expires_at"], "new_expires_at": expires_at,
            "from": lic["status"], "to": to,
            "code_reissued": True, "old_code_fp": _fingerprint(lic["code"]), "new_code_fp": _fingerprint(code)})
        await self.audit.record(actor, "license.extend", f"license:{lid}", self.snapshot(lic), self.snapshot(new))
        return new

    async def suspend(self, actor, lid):
        return await self._transition(lid, "suspend", actor, allowed=(ACTIVE,), to=SUSPENDED, event="suspended")

    async def resume(self, actor, lid):
        return await self._transition(lid, "resume", actor, allowed=(SUSPENDED,), to=ACTIVE, event="resumed")

    async def revoke(self, actor, lid):
        return await self._transition(lid, "revoke", actor, allowed=(PENDING, ACTIVE, SUSPENDED, EXPIRED),
                                      to=REVOKED, event="revoked")

    # ---------- 内部方法（供 L-42 激活、L-40 租约调用）----------
    async def mark_activated(self, lid: str, actor: Optional[Actor] = None, ip: str = "") -> Dict[str, Any]:
        """pending -> active，记录 activated_at。其它状态抛 409。"""
        actor = actor or Actor(None, ip)
        return await self._transition(lid, "activate", actor, allowed=(PENDING,), to=ACTIVE,
                                      extra={"activated_at": self.now()}, event="activated")

    async def expire_due(self) -> int:
        """active 且已到期 -> expired；返回处理条数。可由定时任务调用，列表/详情查询时也会惰性调用。"""
        n = 0
        system = Actor(None, "system")
        for lic in await self.r.licenses.list_due(self.now()):
            new = await self.r.licenses.update(lic["lid"], {"status": EXPIRED}, expect_status=(ACTIVE,))
            if new is not None:
                n += 1
                await self._event(lic["lid"], "expired", system, {"from": ACTIVE, "to": EXPIRED})
                await self.audit.record(system, "license.expire", f"license:{lic['lid']}",
                                        {"status": ACTIVE}, {"status": EXPIRED})
        return n
