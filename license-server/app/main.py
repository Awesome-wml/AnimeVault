"""授权服务入口。启动：

    PYTHONPATH=../license uvicorn app.main:create_app --factory --port 18100
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .api.deps import Ctx
from .api.routes import admin_router, router
from .config import Settings, load_settings
from .db import make_repos
from .errors import ApiError
from .repo.base import Repos
from .services.admins import AdminService
from .services.audit import AuditService
from .services.licenses import LicenseService


def create_app(settings: Optional[Settings] = None, repos: Optional[Repos] = None) -> FastAPI:
    settings = settings or load_settings()  # 配置缺失/占位符 -> ConfigError，进程退出

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        r = repos or make_repos(settings.db)
        await r.ensure_ready()
        await r.keys.upsert(settings.signing_kid, settings.signing_public_key, "active")
        audit = AuditService(r.audit)
        app.state.ctx = Ctx(settings, r, audit, LicenseService(r, settings, audit),
                            AdminService(r, audit, settings.jwt_secret, settings.jwt_ttl_seconds))
        try:
            yield
        finally:
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
    return app
