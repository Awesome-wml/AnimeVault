"""管理员账号管理与登录。"""
from __future__ import annotations

import re
import time
import uuid
from typing import Any, Dict, Optional

from ..errors import ApiError
from ..repo.base import DuplicateError, Repos
from .audit import Actor, AuditService
from .security import (MIN_PASSWORD_LEN, LoginLimiter, burn_dummy, hash_password,
                       make_token, verify_password)

ROLES = ("super", "ops", "readonly")
_USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{2,31}$")
GENERIC_LOGIN_FAIL = "用户名或密码错误"


def public_admin(a: Dict[str, Any]) -> Dict[str, Any]:
    """对外视图：永远不含 password_hash。"""
    return {k: a.get(k) for k in ("id", "username", "role", "enabled", "created_at", "last_login_at")}


def check_password_policy(pw: str) -> None:
    if not isinstance(pw, str) or len(pw) < MIN_PASSWORD_LEN:
        raise ApiError(422, "PASSWORD_TOO_SHORT", f"密码至少 {MIN_PASSWORD_LEN} 位")


class AdminService:
    def __init__(self, repos: Repos, audit: AuditService, jwt_secret: str, jwt_ttl: int,
                 limiter: Optional[LoginLimiter] = None):
        self.r, self.audit, self.secret, self.ttl = repos, audit, jwt_secret, jwt_ttl
        self.limiter = limiter or LoginLimiter()

    async def create(self, actor: Actor, username: str, password: str, role: str,
                     action: str = "admin.create") -> Dict[str, Any]:
        username = username.strip().lower()
        if not _USERNAME_RE.match(username):
            raise ApiError(422, "USERNAME_INVALID", "用户名 3-32 位，小写字母、数字、._-")
        if role not in ROLES:
            raise ApiError(422, "ROLE_INVALID", "角色只能是 super / ops / readonly")
        check_password_policy(password)
        doc = {"id": uuid.uuid4().hex, "username": username, "password_hash": hash_password(password),
               "role": role, "enabled": True, "created_at": int(time.time()), "last_login_at": None,
               "token_valid_after": 0}
        try:
            await self.r.admins.insert(doc)
        except DuplicateError:
            raise ApiError(409, "USERNAME_EXISTS", "用户名已存在") from None
        await self.audit.record(actor, action, f"admin:{doc['id']}", None, public_admin(doc))
        return doc

    async def update(self, actor: Actor, admin_id: str, *, role: Optional[str], enabled: Optional[bool],
                     password: Optional[str]) -> Dict[str, Any]:
        cur = await self.r.admins.get(admin_id)
        if cur is None:
            raise ApiError(404, "ADMIN_NOT_FOUND", "管理员不存在")
        fields: Dict[str, Any] = {}
        if role is not None:
            if role not in ROLES:
                raise ApiError(422, "ROLE_INVALID", "角色只能是 super / ops / readonly")
            fields["role"] = role
        if enabled is not None:
            fields["enabled"] = enabled
        if password is not None:
            check_password_policy(password)
            fields["password_hash"] = hash_password(password)
            fields["token_valid_after"] = int(time.time())  # 重置密码后旧 JWT 作废
        if not fields:
            raise ApiError(422, "NO_CHANGES", "没有要修改的内容")
        was_super = cur["role"] == "super" and cur["enabled"]
        still_super = fields.get("role", cur["role"]) == "super" and fields.get("enabled", cur["enabled"])
        if was_super and not still_super and await self.r.admins.count_enabled_super() <= 1:
            raise ApiError(409, "LAST_SUPER", "不能禁用或降级最后一个超级管理员")
        new = await self.r.admins.update(admin_id, fields)
        await self.audit.record(
            actor, "admin.update", f"admin:{admin_id}", public_admin(cur),
            dict(public_admin(new), password_reset="password" in fields or None))
        return new

    async def login(self, actor_ip: str, username: str, password: str):
        uname = (username or "").strip().lower()
        key = (uname, actor_ip)
        base = Actor(None, actor_ip, uname)
        left = self.limiter.locked_for(key)
        if left:
            await self.audit.record(base, "auth.login_locked", f"admin:{uname}", None, {"retry_after": left})
            raise ApiError(429, "LOGIN_LOCKED", f"登录失败次数过多，请 {left} 秒后再试", {"retry_after": left})
        admin = await self.r.admins.get_by_username(uname)
        ok = False
        if admin is not None:
            ok = verify_password(password or "", admin["password_hash"]) and admin["enabled"]
        else:
            burn_dummy(password or "")
        if not ok:
            locked = self.limiter.record_failure(key)
            await self.audit.record(Actor(admin["id"] if admin else None, actor_ip, uname), "auth.login_failed",
                                    f"admin:{uname}", None, {"locked": locked})
            if locked:
                await self.audit.record(base, "auth.login_locked", f"admin:{uname}", None, {"just_locked": True})
            raise ApiError(401, "LOGIN_FAILED", GENERIC_LOGIN_FAIL)
        self.limiter.record_success(key)
        now = int(time.time())
        await self.r.admins.update(admin["id"], {"last_login_at": now})
        await self.audit.record(Actor(admin["id"], actor_ip, uname), "auth.login_success", f"admin:{admin['id']}")
        token, exp = make_token(self.secret, admin["id"], admin["role"], self.ttl)
        return token, exp, public_admin(dict(admin, last_login_at=now))
