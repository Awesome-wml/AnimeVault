"""审计日志：只写入。敏感字段在入库前统一剔除。"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Optional

SENSITIVE_KEYS = {"password", "password_hash", "code", "code_display", "token", "jwt",
                  "private_key", "signing_private_key", "secret"}


def redact(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: redact(v) for k, v in obj.items() if k not in SENSITIVE_KEYS}
    if isinstance(obj, list):
        return [redact(v) for v in obj]
    return obj


@dataclass
class Actor:
    admin_id: Optional[str]
    ip: str = ""
    username: Optional[str] = None


class AuditService:
    def __init__(self, repo):
        self.repo = repo

    async def record(self, actor: Actor, action: str, target: str,
                     before: Any = None, after: Any = None) -> None:
        await self.repo.insert({
            "admin_id": actor.admin_id, "action": action, "target": target,
            "before": redact(before), "after": redact(after),
            "ip": actor.ip, "at": int(time.time()), "seq": time.time_ns(),
        })
