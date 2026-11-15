"""授权服务入口。启动：

    PYTHONPATH=../license uvicorn app.main:create_app --factory --port 18100
"""
from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .api.deps import Ctx
from .api.client import client_router
from .api.routes import admin_router, router
from .config import Settings, load_settings
from .db import make_repos
from .errors import ApiError
from .repo.base import Repos
from .services.activation import ActivationService
from .services.admins import AdminService
from .services.audit import AuditService
from .services.leases import LeaseService
from .services.licenses import LicenseService
from .services.requests import RequestService


async def _expire_loop(licenses: LicenseService, interval: int) -> None:
    """后台任务：定期把到期的 active 授权置为 expired。单次失败只记日志，不退出。"""
    while True:
        await asyncio.sleep(interval)
        try:
            n = await licenses.expire_due()
            if n:
                logging.getLogger("license.expire").info("expired %d licenses", n)
        except asyncio.CancelledError:
            raise
        except Exception:
            logging.getLogger("license.expire").exception("expire_due failed")


def create_app(settings: Optional[Settings] = None, repos: Optional[Repos] = None,
               clock=time.time) -> FastAPI:
    settings = settings or load_settings()  # 配置缺失/占位符 -> ConfigError，进程退出

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        r = repos or make_repos(settings.db)
        await r.ensure_ready()
        await r.keys.upsert(settings.signing_kid, settings.signing_public_key, "active")
        audit = AuditService(r.audit)
        licenses = LicenseService(r, settings, audit, clock)
        leases = LeaseService(r, settings, licenses, clock=clock)
        app.state.ctx = Ctx(settings, r, audit, licenses,
                            AdminService(r, audit, settings.jwt_secret, settings.jwt_ttl_seconds),
                            leases, ActivationService(leases),
                            RequestService(r, settings, licenses, audit, clock))
        task = None
        if settings.expire_interval_seconds > 0:
            task = asyncio.create_task(_expire_loop(licenses, settings.expire_interval_seconds))
        try:
            yield
        finally:
            if task is not None:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            await r.close()

    app = FastAPI(title="DongAI License Server", lifespan=lifespan, docs_url=None, redoc_url=None,
                  openapi_url=None)

    @app.exception_handler(ApiError)
    async def _api_error(_: Request, e: ApiError):
        return JSONResponse({"code": e.code, "message": e.message, **e.extra}, status_code=e.status)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, e: RequestValidationError):
        fields = [".".join(str(x) for x in err["loc"][1:]) for err in e.errors()]
        return JSONResponse({"code": "VALIDATION_ERROR", "message": "请求参数不合法", "fields": fields},
                            status_code=422)

    app.include_router(router)
    app.include_router(admin_router)
    app.include_router(client_router)
    return app
