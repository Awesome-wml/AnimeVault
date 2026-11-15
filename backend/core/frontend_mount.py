"""桌面模式：由后端同源提供前端构建产物（L-06）。

环境变量 DONGAI_FRONTEND_DIR 指向前端 dist 目录且其中有 index.html 时才挂载，否则什么都不做（非桌面行为不变）。
- 挂在根路径 `/`，前端是 hash 路由，所以 SPA 回落只需要把「不存在的页面路径」返回 index.html；
- `/api`、`/static`、`/docs`、`/redoc`、`/openapi.json`、`/health` 永远不由前端接管（不存在时仍是后端自己的 404）；
- 带扩展名但不存在的路径（如 /js/x.js）返回 404，不回落，避免把 HTML 当脚本；
- 前端页面本身无需令牌/授权即可加载（令牌中间件和授权拦截都只管 /api）。
"""
import logging
import os
from pathlib import Path
from typing import Optional

from fastapi import FastAPI
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.staticfiles import StaticFiles

logger = logging.getLogger(__name__)

FRONTEND_DIR_ENV = "DONGAI_FRONTEND_DIR"
RESERVED = ("api", "static", "docs", "redoc", "openapi.json", "health")


def frontend_dir() -> Optional[Path]:
    raw = os.environ.get(FRONTEND_DIR_ENV, "").strip()
    if not raw:
        return None
    p = Path(raw)
    return p if (p / "index.html").is_file() else None


def _is_reserved(path: str) -> bool:
    first = path.strip("/").split("/", 1)[0]
    return first in RESERVED


class SPAStaticFiles(StaticFiles):
    async def get_response(self, path, scope):
        if _is_reserved(path):
            raise StarletteHTTPException(status_code=404)
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code != 404 or "." in Path(path).name:
                raise
            return await super().get_response("index.html", scope)


def mount_frontend(app: FastAPI) -> bool:
    """在所有后端路由注册完之后调用。挂载成功返回 True。"""
    directory = frontend_dir()
    if directory is None:
        if os.environ.get(FRONTEND_DIR_ENV, "").strip():
            logger.warning("DONGAI_FRONTEND_DIR=%s 下没有 index.html，不挂载前端", os.environ[FRONTEND_DIR_ENV])
        return False
    # 后端自带的 GET / 返回 JSON 说明，桌面模式下让位给前端首页
    app.router.routes[:] = [r for r in app.router.routes
                            if not (getattr(r, "path", None) == "/" and (getattr(r, "methods", None) or set()) <= {"GET", "HEAD"})]
    app.mount("/", SPAStaticFiles(directory=str(directory), html=True), name="frontend")
    logger.info("前端目录挂载: %s", directory)
    return True
