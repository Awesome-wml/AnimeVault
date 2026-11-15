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
        # 设计 7.3：expired 延期后回到 active；但从未激活过的授权（activated_at 为空）延期后仍是待激活。
        # 现状只有 active 会被置为 expired（expire_due），pending 到期未激活保持 pending；这里是防御性处理，
        # 避免历史/外部写入的「未激活却 expired」的记录被延期成 active（绕过激活）。
        if lic["status"] == EXPIRED:
            to = ACTIVE if lic.get("activated_at") else PENDING
        else:
            to = lic["status"]
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

    # ---------- 设备与会话（L-45）----------
    @staticmethod
    def device_view(d: Dict[str, Any], current: bool = False) -> Dict[str, Any]:
        """设备对外视图：不返回原始分量哈希全文，只给前 6 位用于辨识。"""
        mc = d.get("mc") or []
        return {"did": d["did"], "components_count": len(mc), "components_hint": [str(x)[:6] for x in mc],
                "first_seen_at": d.get("first_seen_at"), "last_seen_at": d.get("last_seen_at"),
                "last_ip": d.get("last_ip"), "app_version": d.get("app_version"),
                "bound": bool(d.get("bound", True)), "unbound_at": d.get("unbound_at"), "is_current": current}

    async def _session_components(self, lic: Dict[str, Any]) -> Optional[List[str]]:
        sid = lic.get("active_sid")
        lease = await self.r.leases.get(lic["lid"], sid) if sid else None
        return lease.get("mc") if lease else None

    async def list_devices(self, lid: str) -> List[Dict[str, Any]]:
        lic = await self._get_fresh(lid)
        cur = await self._session_components(lic)
        out = []
        for d in await self.r.devices.list_for(lid):
            is_cur = bool(cur) and bool(d.get("bound", True)) and lt.components_match(d["mc"], cur)
            out.append(self.device_view(d, is_cur))
        return out

    async def _kick_session(self, lic: Dict[str, Any], actor: Actor, via: str) -> int:
        """active_sid 置空 + 该授权所有未撤销租约标 revoked + 写 session_kicked 事件。返回撤销的租约数。"""
        lid = lic["lid"]
        await self.r.licenses.update(lid, {"active_sid": None},
                                     expect_status=(PENDING, ACTIVE, SUSPENDED, EXPIRED))
        n = await self.r.leases.revoke_others(lid, "")  # sid 不会是空串：等于撤销全部
        await self._event(lid, "session_kicked", actor, {"sid": (lic.get("active_sid") or "")[:6],
                                                         "leases_revoked": n, "via": via})
        return n

    async def kick(self, actor: Actor, lid: str) -> Dict[str, Any]:
        """踢下线：客户端下次续租收到 LICENSE_SESSION_CONFLICT，用授权码重新激活即可。"""
        lic = await self._get_fresh(lid)
        if lic["status"] == REVOKED:
            raise _state_error(lic, "kick")
        if not lic.get("active_sid"):
            raise ApiError(409, "NO_ACTIVE_SESSION", "该授权当前没有在线会话")
        n = await self._kick_session(lic, actor, "kick")
        new = await self.r.licenses.get(lid)
        await self.audit.record(actor, "license.kick", f"license:{lid}",
                                {"active_sid": (lic.get("active_sid") or "")[:6]},
                                {"active_sid": None, "leases_revoked": n})
        return new

    async def unbind_device(self, actor: Actor, lid: str, did: str) -> Dict[str, Any]:
        lic = await self._get_fresh(lid)
        if lic["status"] == REVOKED:
            raise _state_error(lic, "unbind")
        devs = await self.r.devices.list_for(lid)
        dev = next((d for d in devs if d["did"] == did), None)
        if dev is None:
            raise ApiError(404, "DEVICE_NOT_FOUND", "设备不存在")
        if not dev.get("bound", True):
            raise ApiError(409, "DEVICE_NOT_BOUND", "该设备已解绑")
        cur = await self._session_components(lic)
        if cur is None and lic.get("active_sid"):  # 没有租约记录：只有一台绑定设备时视为它
            is_session_device = sum(1 for d in devs if d.get("bound", True)) == 1
        else:
            is_session_device = bool(cur) and lt.components_match(dev["mc"], cur)
        new = await self.r.devices.update(lid, did, {"bound": False, "unbound_at": self.now()})
        kicked = False
        if lic.get("active_sid") and is_session_device:
            await self._kick_session(lic, actor, "unbind")
            kicked = True
        await self._event(lid, "device_unbound", actor, {"did": did, "kicked": kicked})
        await self.audit.record(actor, "license.device_unbind", f"license:{lid}",
                                {"did": did, "bound": True}, {"did": did, "bound": False, "kicked": kicked})
        return {"device": self.device_view(new), "kicked": kicked}

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
