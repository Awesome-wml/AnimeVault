"""客户端接口 /license/v1（不需要管理员登录）。错误统一 {code, message}。"""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from ..errors import ApiError
from .deps import Ctx, client_ip, ctx

client_router = APIRouter(prefix="/license/v1")

Comps = List[str]


def _comps(v: Comps) -> Comps:
    out = [x.strip() for x in v if isinstance(x, str) and x.strip()]
    if not out or any(len(x) > 128 for x in out):
        raise ApiError(400, "LICENSE_INVALID", "机器码参数无效")
    return out


class ActivateReq(BaseModel):
    license_code: str = Field(min_length=1, max_length=4096)
    machine_components: Comps = Field(min_length=1, max_length=16)
    app_version: str = Field(default="", max_length=64)
    sid: Optional[str] = Field(default=None, max_length=128)  # 预留：会话 ID 由服务端生成，此字段被忽略


class RenewReq(BaseModel):
    lease: str = Field(min_length=1, max_length=4096)
    machine_components: Comps = Field(min_length=1, max_length=16)
    app_version: str = Field(default="", max_length=64)


class RequestSubmit(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    machine_code: str = Field(min_length=1, max_length=512)
    note: Optional[str] = Field(default=None, max_length=500)


@client_router.post("/request")
async def submit_request(body: RequestSubmit, request: Request, c: Ctx = Depends(ctx)):
    """提交申请单：无需登录，每 IP 每小时 5 次。"""
    return await c.requests.submit(body.email, body.machine_code, body.note, client_ip(request))


@client_router.post("/activate")
async def activate(body: ActivateReq, request: Request, c: Ctx = Depends(ctx)):
    return await c.activation.activate(body.license_code, _comps(body.machine_components),
                                       body.app_version, client_ip(request))


@client_router.post("/renew")
async def renew(body: RenewReq, request: Request, c: Ctx = Depends(ctx)):
    return await c.client.renew(body.lease.strip(), _comps(body.machine_components),
                                body.app_version, client_ip(request))


@client_router.get("/status")
async def status(request: Request, c: Ctx = Depends(ctx)):
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer ") or not auth[7:].strip():
        raise ApiError(401, "LICENSE_INVALID", "缺少租约")
    raw = request.headers.get("x-machine-components", "")
    return await c.client.status(auth[7:].strip(), _comps(raw.split(",")))
