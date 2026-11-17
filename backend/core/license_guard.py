"""全局授权拦截（纯 ASGI 中间件，不缓冲 SSE 流）。

- 桌面模式（DONGAI_DESKTOP=1）一律启用，无法被环境变量关闭；
- 非桌面模式默认不启用，仅 DONGAI_LICENSE_ENFORCE=1 时启用（现有测试/e2e 不受影响）；
- 放行：OPTIONS、/health、/docs、/openapi.json、/static/*、/api/license/*，以及所有非 /api 的 HTTP 路径
  （桌面模式下后端同源提供前端页面 `/`、`/js/*` 等，必须能在未激活时加载出激活页；授权拦截只针对 /api）；
- valid / grace：完整放行；
- expired / suspended / lease_expired：只读模式，GET/HEAD/OPTIONS 放行，其余方法返回
  403 {"code": "LICENSE_READONLY", "state", "message"}（视频/出图/LLM 调用都是 POST，自然被拦；WebSocket 也拦）；
- 其余状态（unactivated、invalid、machine_mismatch、revoked、session_conflict、clock_rollback）完全拦截，
  返回 403 {"code": "LICENSE_REQUIRED", "state", "message"}；
- 例外：只读状态下 POST /api/auth/local-session 放行（接口内部会再校验一次授权状态）；
- 默认拒绝、出错也拒绝（fail closed）；
- update_required（强制升级，core/update_checker.py）：优先于授权状态，除下面放行的路径外所有 /api 接口（含 GET、WebSocket）
  一律 403 {"code": "UPDATE_REQUIRED", "state": "update_required", "min_supported", "message"}，不是只读；
  只拦截请求，本地数据原封不动。/api/license/*、/api/update/*、/health 仍放行（激活页、升级页要用）。
顺序：先过本地令牌（core/local_token.py），再过授权，所以 main.py 里要先添加本中间件、后添加令牌中间件。
"""
import json
import logging
import os

from config import paths

logger = logging.getLogger(__name__)

ENFORCE_ENV = "DONGAI_LICENSE_ENFORCE"
FULL_STATES = frozenset({"valid", "grace"})
READONLY_STATES = frozenset({"expired", "suspended", "lease_expired"})
READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
_READONLY_MESSAGES = {
    "expired": "授权已到期，当前为只读模式，请联系我们续期",
    "suspended": "授权已被停用，当前为只读模式，请联系管理员",
    "lease_expired": "离线时间过长，当前为只读模式，请联网后续租",
}
LOCAL_SESSION_PATH = "/api/auth/local-session"
DEV_ENV = "DONGAI_LICENSE_DEV"
EXEMPT_EXACT = {"/health", "/docs", "/openapi.json", "/api/license", "/api/update"}
EXEMPT_PREFIX = ("/static/", "/api/license/", "/api/update/")


def enforcement_enabled() -> bool:
    if paths.is_desktop():
        return True
    return os.environ.get(ENFORCE_ENV, "").strip() == "1"


def license_mode_enabled() -> bool:
    """授权模式：桌面模式，或 DONGAI_LICENSE_DEV=1（开发联调）。该模式下由授权码本身充当身份，不用账号登录/注册。"""
    if paths.is_desktop():
        return True
    return os.environ.get(DEV_ENV, "").strip() == "1"


def is_exempt(scope) -> bool:
    if scope.get("type") == "http" and scope.get("method") == "OPTIONS":
        return True
    path = scope.get("path", "")
    if scope.get("type") == "http" and not (path == "/api" or path.startswith("/api/")):
        return True
    return path in EXEMPT_EXACT or path.startswith(EXEMPT_PREFIX)


def _update_required():
    """强制升级信息（dict）或 None；读取异常不拦截（它不是授权判断）。"""
    try:
        from core import update_checker
        return update_checker.get_checker().required_info()
    except Exception:
        logger.exception("强制升级状态检查失败")
        return None


def _current_state() -> str:
    """返回授权状态值；任何异常都按无效处理。"""
    try:
        from core import license_client
        return license_client.get_client().status()["state"]
    except Exception:
        logger.exception("授权状态检查失败，按未授权处理")
        return "invalid"


async def _send_update_required(send, upd):
    upd = upd or {}
    message = upd.get("message") or "当前版本过低，请升级到新版本后继续使用"
    body = json.dumps({"code": "UPDATE_REQUIRED", "state": "update_required", "message": message,
                       "detail": message, "min_supported": upd.get("min_supported")},
                      ensure_ascii=False).encode("utf-8")
    await send({"type": "http.response.start", "status": 403,
                "headers": [(b"content-type", b"application/json; charset=utf-8"),
                            (b"content-length", str(len(body)).encode())]})
    await send({"type": "http.response.body", "body": body})


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
            upd = _update_required()
            state = "update_required" if upd else _current_state()
        except Exception:
            logger.exception("授权拦截判断异常，按未授权处理")
            state, upd = "invalid", None
        if state in FULL_STATES:
            return await self.app(scope, receive, send)
        if stype == "http" and state in READONLY_STATES and scope.get("method") in READ_METHODS:
            return await self.app(scope, receive, send)
        if (stype == "http" and state in READONLY_STATES and scope.get("method") == "POST"
                and scope.get("path") == LOCAL_SESSION_PATH):
            # 只读模式也要能拿到本地会话，才能查看已有数据；其余写操作仍被拦
            return await self.app(scope, receive, send)
        if stype == "websocket":
            # 先吞掉握手消息再拒绝
            await receive()
            return await send({"type": "websocket.close", "code": 4403})
        if state == "update_required":
            return await _send_update_required(send, upd)
        if state in READONLY_STATES:
            code, message = "LICENSE_READONLY", _READONLY_MESSAGES[state]
        else:
            code, message = "LICENSE_REQUIRED", "需要先激活授权后才能使用"
        body = json.dumps({"code": code, "state": state, "message": message,
                           "detail": message}, ensure_ascii=False).encode("utf-8")
        await send({"type": "http.response.start", "status": 403,
                    "headers": [(b"content-type", b"application/json; charset=utf-8"),
                                (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})
