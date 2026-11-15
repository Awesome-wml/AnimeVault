"""激活与设备绑定（设计 4.2、6、7.3）。

流程：规范化授权码 -> 验签 -> 查记录 -> code 必须等于记录里当前有效的 code -> 状态检查
-> 设备绑定（容差匹配、dev_max）-> 新会话 sid（顶掉旧会话）-> 签发租约。
授权码原文不进日志、不进事件（旧码只记指纹）。
"""
from __future__ import annotations

import hashlib
import hmac
import asyncio
import logging
import secrets
import time
from typing import Any, Dict, List

from dongai_license import license_token as lt

from ..errors import ApiError
from .audit import Actor
from .leases import (LeaseService, e_expired, e_invalid, e_mismatch, new_sid,
                     sid6)
from .licenses import ACTIVE, PENDING

log = logging.getLogger("license.client")

ACTIVATE_IP_LIMIT = 20   # 每 IP 每分钟
ACTIVATE_LID_LIMIT = 10  # 每授权每分钟
BIND_LOCK_TTL = 10       # 设备绑定互斥锁有效期（秒），持有者崩溃后自动失效
BIND_LOCK_WAIT = 8       # 等锁最长时间（秒）


def _fp(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()[:12]


class ActivationService:
    def __init__(self, leases: LeaseService):
        self.l = leases
        self.r, self.s = leases.r, leases.s

    async def _lock_bind(self, lid: str, owner: str) -> None:
        deadline = time.monotonic() + BIND_LOCK_WAIT
        while not await self.r.devices.lock(lid, owner, time.time(), BIND_LOCK_TTL):
            if time.monotonic() > deadline:
                raise ApiError(503, "SERVER_BUSY", "服务繁忙，请稍后重试")
            await asyncio.sleep(0.005 + secrets.randbelow(15) / 1000)

    async def activate(self, code: str, comps: List[str], app_version: str, ip: str) -> Dict[str, Any]:
        l = self.l
        l.limiter.hit(f"act-ip:{ip}", ACTIVATE_IP_LIMIT)
        try:
            norm = lt.normalize_input(code)
            keys = l.public_keys()
            # 先只验签取 lid（机器码不匹配时也要能把事件记到对应授权上）
            payload = lt._parse_and_verify(norm, "license", lt._LICENSE_TYPES, keys)
        except lt.LicenseError:
            raise e_invalid("授权码无效") from None
        lid = payload["lid"]
        l.limiter.hit(f"act-lid:{lid}", ACTIVATE_LID_LIMIT)
        lic = await self.r.licenses.get(lid)
        if lic is None:
            raise e_invalid("授权码无效")
        now = l.now()

        try:
            lt.verify_license(norm, keys, comps, now=now)
        except lt.MachineMismatch:
            await l.event(lid, "machine_mismatch", ip, {"reason": "授权码与本机不符", "app_version": app_version[:32]})
            log.warning("activate machine_mismatch lid=%s", lid)
            raise e_mismatch() from None
        except lt.LicenseExpired:
            raise e_expired() from None
        except lt.LicenseError:
            raise e_invalid("授权码无效") from None

        # 授权码必须是记录里当前有效的那一个（延期会重签，旧码作废）
        if not hmac.compare_digest((lic.get("code") or "").encode(), norm.encode()):
            await l.event(lid, "activation_rejected", ip, {"reason": "旧码", "code_fp": _fp(norm)})
            log.warning("activate old_code lid=%s", lid)
            raise e_invalid("授权码无效")

        # 状态
        was_pending = lic["status"] == PENDING
        if lic["status"] == PENDING and int(lic["expires_at"]) > now:
            try:
                await l.licenses.mark_activated(lid, Actor(None, ip))
            except ApiError as e:
                if e.status != 409:
                    raise
            lic = await self.r.licenses.get(lid)  # 并发下可能已被别人激活或改了状态
        await l.check_status(lic)

        # 设备绑定：读已绑定 -> 判断 -> 写入必须互斥，否则并发激活会重复绑定同一设备、绕过 dev_max
        owner = secrets.token_hex(8)
        await self._lock_bind(lid, owner)
        try:
            bound = [d for d in await self.r.devices.list_for(lid) if d.get("bound", True)]
            same_machine = (lt.components_match(lic["machine_components"], comps)
                            or any(lt.components_match(d["mc"], comps) for d in bound))
            if not same_machine:
                await l.event(lid, "machine_mismatch", ip, {"reason": "与绑定设备不符", "app_version": app_version[:32]})
                raise e_mismatch()
            device = next((d for d in bound if lt.components_match(d["mc"], comps)), None)
            if device is None:
                if len(bound) >= int(lic["dev_max"]):
                    await l.event(lid, "machine_mismatch", ip, {"reason": "设备数超过上限", "bound": len(bound),
                                                                "app_version": app_version[:32]})
                    raise e_mismatch()
                await self.r.devices.insert({
                    "lid": lid, "did": "dev_" + secrets.token_hex(6), "mc": list(comps), "first_seen_at": now,
                    "last_seen_at": now, "last_ip": ip, "app_version": app_version[:32], "bound": True,
                    "unbound_at": None})
                await l.event(lid, "device_bound", ip, {"devices": len(bound) + 1})
            else:  # 硬件小变更：更新为最新分量
                await self.r.devices.update(lid, device["did"], {
                    "mc": list(comps), "last_seen_at": now, "last_ip": ip, "app_version": app_version[:32]})

        finally:
            await self.r.devices.unlock(lid, owner)

        # 新会话：后一次激活获胜，旧会话下次续租收到 SESSION_CONFLICT
        sid, prev_sid = new_sid(), lic.get("active_sid")
        token, exp = l.sign_lease(lic, sid, comps)
        new = await self.r.licenses.update(lid, {
            "active_sid": sid, "last_seen_at": now, "last_seen_ip": ip, "last_renew_at": now},
            expect_status=(ACTIVE,))
        if new is None:  # 状态刚被管理员改了
            await l.check_status(await self.r.licenses.get(lid))
            raise e_invalid()
        await self.r.leases.upsert(lid, sid, {"mc": list(comps), "issued_at": now, "expires_at": exp,
                                              "ip": ip, "revoked": False})
        await self.r.leases.revoke_others(lid, sid)
        if prev_sid and prev_sid != sid:
            await l.event(lid, "session_replaced", ip, {"old_sid": sid6(prev_sid), "new_sid": sid6(sid)})
        if not was_pending:  # 重复激活（首次激活事件由 mark_activated 写）
            await l.event(lid, "renewed", ip, {"via": "activate", "sid": sid6(sid)})
        log.info("activate ok lid=%s sid=%s", lid, sid6(sid))
        return {"lease": token, "expires_at": exp, "server_time": now, "license": l.license_view(new)}
