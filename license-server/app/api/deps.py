from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from fastapi import Depends, Request

from ..config import Settings
from ..errors import ApiError
from ..repo.base import Repos
from ..services.activation import ActivationService
from ..services.admins import AdminService
from ..services.audit import Actor, AuditService
from ..services.leases import LeaseService
from ..services.licenses import LicenseService
from ..services.releases import ReleaseService
from ..services.requests import RequestService
from ..services.security import decode_token

READ = ("super", "ops", "readonly")
WRITE = ("super", "ops")
SUPER = ("super",)


@dataclass
class Ctx:
    settings: Settings
    repos: Repos
    audit: AuditService
    licenses: LicenseService
    admins: AdminService
    client: LeaseService = None  # type: ignore[assignment]
    activation: ActivationService = None  # type: ignore[assignment]
    requests: RequestService = None  # type: ignore[assignment]
    releases: ReleaseService = None  # type: ignore[assignment]


def ctx(request: Request) -> Ctx:
    return request.app.state.ctx


def client_ip(request: Request) -> str:
    # 不信任 X-Forwarded-For；放在反向代理后时由代理层保证来源并在部署时另行处理
    return request.client.host if request.client else ""


async def current_admin(request: Request, c: Ctx = Depends(ctx)) -> dict:
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        raise ApiError(401, "UNAUTHENTICATED", "未登录")
    payload = decode_token(c.settings.jwt_secret, auth[7:].strip())
    if not payload or not payload.get("admin_id"):
        raise ApiError(401, "UNAUTHENTICATED", "登录已失效，请重新登录")
    admin = await c.repos.admins.get(payload["admin_id"])
    if (admin is None or not admin["enabled"]
            or int(payload.get("iat", 0)) < int(admin.get("token_valid_after", 0))):
        raise ApiError(401, "UNAUTHENTICATED", "登录已失效，请重新登录")
    return admin


def require(*roles: str):
    async def dep(admin: dict = Depends(current_admin)) -> dict:
        if admin["role"] not in roles:  # 角色以库里最新值为准
            raise ApiError(403, "FORBIDDEN", "没有权限执行此操作")
        return admin
    return dep


def actor_of(admin: Optional[dict], request: Request) -> Actor:
    return Actor(admin["id"] if admin else None, client_ip(request), admin["username"] if admin else None)
