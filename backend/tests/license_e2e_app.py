"""授权 e2e 专用的最小后端：只含授权接口 + 全局拦截 + 一个受保护的占位接口，不连 Mongo/Redis。
由 scripts/e2e-license.sh 启动（PYTHONPATH 指向 backend/）。"""
from fastapi import FastAPI

from api import license as license_api
from core.license_guard import LicenseGuardMiddleware
from core.local_token import LocalTokenMiddleware

app = FastAPI()
app.include_router(license_api.router)


@app.get("/health")
async def health():
    return {"status": "healthy"}


@app.get("/api/projects")
async def projects():
    return {"data": []}


@app.post("/api/projects")
async def create_project():
    return {"data": {"id": "p1"}}


app.add_middleware(LicenseGuardMiddleware)
app.add_middleware(LocalTokenMiddleware)
