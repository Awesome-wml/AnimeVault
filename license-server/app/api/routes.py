from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field, field_validator

from dongai_license.license_token import format_for_display

from ..services.admins import public_admin
from ..services.licenses import FEATURE_PATTERN
from .deps import READ, SUPER, WRITE, Ctx, actor_of, client_ip, ctx, require

router = APIRouter()
admin_router = APIRouter(prefix="/admin/api")


def _epoch(v):
    if isinstance(v, datetime):
        if v.tzinfo is None:
            v = v.replace(tzinfo=timezone.utc)
        return int(v.timestamp())
    return v


def _parse_exp(v):
    if isinstance(v, str) and not v.strip().lstrip("-").isdigit():
        return _epoch(datetime.fromisoformat(v.replace("Z", "+00:00")))
    return v


class IssueReq(BaseModel):
    machine_code: str = Field(min_length=1, max_length=512)
    plan: str
    features: List[str] = Field(default_factory=list, max_length=50)
    expires_at: int  # Unix 秒；也接受 ISO 时间字符串（无时区按 UTC）
    uid: Optional[str] = Field(default=None, max_length=200)
    email: Optional[str] = Field(default=None, max_length=200)
    dev_max: int = Field(default=1, ge=1, le=100)
    note: Optional[str] = Field(default=None, max_length=500)

    _exp = field_validator("expires_at", mode="before")(_parse_exp)


class ExtendReq(BaseModel):
    expires_at: int

    _exp = field_validator("expires_at", mode="before")(_parse_exp)


class LoginReq(BaseModel):
    username: str = Field(max_length=64)
    password: str = Field(max_length=256)


class AdminCreateReq(BaseModel):
    username: str
    password: str = Field(max_length=256)
    role: str


class AdminUpdateReq(BaseModel):
    role: Optional[str] = None
    enabled: Optional[bool] = None
    password: Optional[str] = Field(default=None, max_length=256)


def lic_view(lic: dict, with_code: bool = True) -> dict:
    out = dict(lic)
    out.setdefault("created_by_username", None)  # 历史记录没有该字段
    code = out.pop("code", None)
    if with_code:
        out["code"] = code
        out["code_display"] = format_for_display(code) if code else None
    return out


@router.get("/health")
async def health():
    return {"status": "ok"}


@admin_router.post("/auth/login")
async def login(body: LoginReq, request: Request, c: Ctx = Depends(ctx)):
    token, exp, admin = await c.admins.login(client_ip(request), body.username, body.password)
    return {"token": token, "token_type": "bearer", "expires_at": exp, "admin": admin}


@admin_router.get("/meta")
async def meta(admin: dict = Depends(require(*READ)), c: Ctx = Depends(ctx)):
    """给管理端的配置：套餐白名单、功能点格式规则、机器码要求，前端不再硬编码。"""
    return {"plans": list(c.settings.plans),
            "features": {"pattern": FEATURE_PATTERN, "max_length": 40, "max_count": 50,
                         "candidates": list(c.settings.feature_candidates)},
            "dev_max": {"min": 1, "max": 100},
            "machine_code": {"min_components": 2},
            "request_rate_limit": {"per_ip": 5, "window_seconds": 3600}}


@admin_router.get("/auth/me")
async def me(admin: dict = Depends(require(*READ))):
    return public_admin(admin)


# ---------- 授权 ----------
@admin_router.post("/licenses", status_code=201)
async def issue(body: IssueReq, request: Request, admin: dict = Depends(require(*WRITE)), c: Ctx = Depends(ctx)):
    res = await c.licenses.issue(actor_of(admin, request), **body.model_dump())
    return {"license": lic_view(res["license"]), "same_machine_count": res["same_machine_count"],
            "warnings": res["warnings"]}


@admin_router.get("/licenses")
async def list_licenses(status: Optional[str] = None, email: Optional[str] = None, lid: Optional[str] = None,
                        page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                        admin: dict = Depends(require(*READ)), c: Ctx = Depends(ctx)):
    items, total = await c.licenses.list(status=status, email=email, lid=lid, page=page, page_size=page_size)
    return {"items": [lic_view(i, with_code=False) for i in items], "total": total,
            "page": page, "page_size": page_size}


@admin_router.get("/licenses/{lid}")
async def get_license(lid: str, admin: dict = Depends(require(*READ)), c: Ctx = Depends(ctx)):
    return lic_view(await c.licenses.get(lid))


@admin_router.get("/licenses/{lid}/events")
async def license_events(lid: str, page: int = Query(1, ge=1), page_size: int = Query(100, ge=1, le=100),
                         order: str = Query("desc", pattern="^(asc|desc)$"),
                         admin: dict = Depends(require(*READ)), c: Ctx = Depends(ctx)):
    items, total = await c.licenses.events(lid, page=page, page_size=page_size, desc=order == "desc")
    for e in items:
        e.setdefault("actor_username", None)  # 历史事件没有该字段
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@admin_router.post("/licenses/{lid}/extend")
async def extend(lid: str, body: ExtendReq, request: Request, admin: dict = Depends(require(*WRITE)),
                 c: Ctx = Depends(ctx)):
    return lic_view(await c.licenses.extend(actor_of(admin, request), lid, body.expires_at))


def _transition_route(name: str):
    async def handler(lid: str, request: Request, admin: dict = Depends(require(*WRITE)), c: Ctx = Depends(ctx)):
        return lic_view(await getattr(c.licenses, name)(actor_of(admin, request), lid))
    handler.__name__ = name
    admin_router.post(f"/licenses/{{lid}}/{name}")(handler)


for _n in ("suspend", "resume", "revoke"):
    _transition_route(_n)


# ---------- 管理员 ----------
@admin_router.post("/admins", status_code=201)
async def create_admin(body: AdminCreateReq, request: Request, admin: dict = Depends(require(*SUPER)),
                       c: Ctx = Depends(ctx)):
    return public_admin(await c.admins.create(actor_of(admin, request), body.username, body.password, body.role))


@admin_router.get("/admins")
async def list_admins(page: int = Query(1, ge=1), page_size: int = Query(100, ge=1, le=100),
                      admin: dict = Depends(require(*SUPER)), c: Ctx = Depends(ctx)):
    rows, total = await c.repos.admins.page((page - 1) * page_size, page_size)
    return {"items": [public_admin(a) for a in rows], "total": total, "page": page, "page_size": page_size}


@admin_router.put("/admins/{admin_id}")
async def update_admin(admin_id: str, body: AdminUpdateReq, request: Request,
                       admin: dict = Depends(require(*SUPER)), c: Ctx = Depends(ctx)):
    return public_admin(await c.admins.update(actor_of(admin, request), admin_id, role=body.role,
                                              enabled=body.enabled, password=body.password))


# ---------- 审计（只读）----------
@admin_router.get("/audit")
async def audit_list(action: Optional[str] = None, admin_id: Optional[str] = None,
                     page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                     admin: dict = Depends(require(*WRITE)), c: Ctx = Depends(ctx)):
    items, total = await c.repos.audit.search(action=action, admin_id=admin_id,
                                              skip=(page - 1) * page_size, limit=page_size)
    for it in items:
        it.setdefault("admin_username", None)  # 历史记录没有该字段，前端用 admin_id 前 8 位兜底
    return {"items": items, "total": total, "page": page, "page_size": page_size}
