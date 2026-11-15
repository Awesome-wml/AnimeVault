"""全局授权拦截（纯 ASGI 中间件，不缓冲 SSE 流）。

- 桌面模式（DONGAI_DESKTOP=1）一律启用，无法被环境变量关闭；
- 非桌面模式默认不启用，仅 DONGAI_LICENSE_ENFORCE=1 时启用（现有测试/e2e 不受影响）；
- 放行：OPTIONS、/health、/docs、/openapi.json、/static/*、/api/license/*，以及所有非 /api 的 HTTP 路径
  （桌面模式下后端同源提供前端页面 `/`、`/js/*` 等，必须能在未激活时加载出激活页；授权拦截只针对 /api）；
- 其余请求在授权无效时返回 403 {"code": "LICENSE_REQUIRED", "state", "message"}；
- 默认拒绝、出错也拒绝（fail closed）。
顺序：先过本地令牌（core/local_token.py），再过授权，所以 main.py 里要先添加本中间件、后添加令牌中间件。
"""
import json
import logging
import os

from config import paths

logger = logging.getLogger(__name__)

ENFORCE_ENV = "DONGAI_LICENSE_ENFORCE"
EXEMPT_EXACT = {"/health", "/docs", "/openapi.json", "/api/license"}
EXEMPT_PREFIX = ("/static/", "/api/license/")


def enforcement_enabled() -> bool:
    if paths.is_desktop():
        return True
    return os.environ.get(ENFORCE_ENV, "").strip() == "1"


def is_exempt(scope) -> bool:
    if scope.get("type") == "http" and scope.get("method") == "OPTIONS":
        return True
    path = scope.get("path", "")
    if scope.get("type") == "http" and not (path == "/api" or path.startswith("/api/")):
        return True
    return path in EXEMPT_EXACT or path.startswith(EXEMPT_PREFIX)


def _current_state() -> str:
    """返回授权状态值；任何异常都按无效处理。"""
    try:
        from core import license_client
        return license_client.get_client().status()["state"]
    except Exception:
        logger.exception("授权状态检查失败，按未授权处理")
        return "invalid"


class LicenseGuardMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        stype = scope["type"]
        if stype not in ("http", "websocket"):
            return await self.app(scope, receive, send)
        try:
            enabled = enforcement_enabled()
            if not enabled or is_exempt(scope):
                return await self.app(scope, receive, send)
            state = _current_state()
        except Exception:
            logger.exception("授权拦截判断异常，按未授权处理")
            state = "invalid"
        if state == "valid":
            return await self.app(scope, receive, send)
        if stype == "websocket":
            # 先吞掉握手消息再拒绝
            await receive()
            return await send({"type": "websocket.close", "code": 4403})
        message = "需要先激活授权后才能使用"
        body = json.dumps({"code": "LICENSE_REQUIRED", "state": state, "message": message,
                           "detail": message}, ensure_ascii=False).encode("utf-8")
        await send({"type": "http.response.start", "status": 403,
                    "headers": [(b"content-type", b"application/json; charset=utf-8"),
                                (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})
