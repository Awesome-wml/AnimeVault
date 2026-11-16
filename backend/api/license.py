"""授权接口（L-26 / L-41）：不需要登录，也不被全局授权拦截。"""
import logging
import threading
import time
from collections import deque

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from core import license_client
from core.license_client import (
    LicenseError, LicenseExpired, LicenseInvalid, MachineMismatch, MachineCodeUnavailable,
    LicenseServerError, LicenseServerUnreachable, NotActivated,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/license", tags=["授权"])

_FRIENDLY = {
    "LICENSE_INVALID": "授权码无效，请检查是否复制完整",
    "LICENSE_MACHINE_MISMATCH": "这个授权码不是本机的，请使用本机机器码申请授权",
    "LICENSE_EXPIRED": "授权码已过期，请联系我们续期",
    "LICENSE_SUSPENDED": "授权已被停用，请联系管理员",
    "LICENSE_REVOKED": "授权已被吊销，请联系我们",
    "LICENSE_SESSION_CONFLICT": "该授权已在另一台设备上使用，重新激活会让对方下线",
    "LEASE_EXPIRED": "离线时间过长，请联网后重新激活",
    "RATE_LIMITED": "操作太频繁，请稍后再试",
    "LICENSE_SERVER_UNREACHABLE": "无法连接授权服务，请检查网络后重试",
    "LICENSE_NOT_ACTIVATED": "本机尚未激活，请先输入授权码",
}
# 注意不用 401：前端对 401 会当作登录过期处理
_STATUS = {
    "LICENSE_INVALID": 400, "LICENSE_MACHINE_MISMATCH": 403, "LICENSE_EXPIRED": 403,
    "LICENSE_SUSPENDED": 403, "LICENSE_REVOKED": 403, "LICENSE_SESSION_CONFLICT": 409,
    "LEASE_EXPIRED": 403, "RATE_LIMITED": 429, "LICENSE_SERVER_UNREACHABLE": 503,
    "LICENSE_NOT_ACTIVATED": 409,
}

RENEW_NOW_LIMIT = 3          # 手动续租：每分钟最多 3 次
RENEW_NOW_WINDOW = 60.0


class ActivateBody(BaseModel):
    code: str = ""


class _SlidingLimiter:
    def __init__(self, limit: int, window: float, clock=time.monotonic):
        self.limit, self.window, self.clock = limit, window, clock
        self._hits = deque()
        self._lock = threading.Lock()

    def allow(self) -> bool:
        now = self.clock()
        with self._lock:
            while self._hits and now - self._hits[0] >= self.window:
                self._hits.popleft()
            if len(self._hits) >= self.limit:
                return False
            self._hits.append(now)
            return True


_renew_limiter = _SlidingLimiter(RENEW_NOW_LIMIT, RENEW_NOW_WINDOW)


def _error(code: str, status: int, message: str, **extra) -> JSONResponse:
    return JSONResponse(status_code=status, content={"code": code, "message": message, "detail": message, **extra})


def _machine_code_error() -> JSONResponse:
    return _error("MACHINE_CODE_UNAVAILABLE", 503, "无法读取本机硬件信息，请联系我们")


def _server_error(e: LicenseServerError) -> JSONResponse:
    code = e.code if e.code in _STATUS else "LICENSE_INVALID"
    return _error(code, _STATUS[code], _FRIENDLY[code])


def _unreachable() -> JSONResponse:
    return _error("LICENSE_SERVER_UNREACHABLE", 503, _FRIENDLY["LICENSE_SERVER_UNREACHABLE"])


@router.get("/machine-code")
async def machine_code():
    try:
        code = license_client.get_machine_code()
    except MachineCodeUnavailable:
        return _machine_code_error()
    return {"machine_code": code, "groups": code.split("-")}


def _public_status(st: dict) -> dict:
    st = dict(st)
    st.pop("server_blocked", None)  # 内部字段
    return st


@router.get("/status")
async def status():
    return _public_status(license_client.get_client().status())


# 下面两个接口会联网（最长 10 秒），用同步函数让 FastAPI 放到线程池里跑，不阻塞事件循环。
@router.post("/activate")
def activate(body: ActivateBody):
    try:
        return _public_status(license_client.get_client().activate(body.code))
    except MachineCodeUnavailable:
        return _machine_code_error()
    except LicenseServerError as e:
        return _server_error(e)
    except LicenseServerUnreachable:
        return _unreachable()
    except (LicenseInvalid, LicenseExpired, MachineMismatch) as e:
        # 只用错误类型，不外泄内部细节（如 kid 未知）
        return _error(e.code, _STATUS[e.code], _FRIENDLY[e.code])
    except LicenseError:
        return _error("LICENSE_INVALID", 400, _FRIENDLY["LICENSE_INVALID"])
    except Exception:
        logger.exception("激活失败")
        return _error("LICENSE_INVALID", 400, _FRIENDLY["LICENSE_INVALID"])


@router.post("/renew-now")
def renew_now():
    """手动触发一次续租（「立即检查」按钮）。每分钟最多 3 次。"""
    if not _renew_limiter.allow():
        return _error("RATE_LIMITED", 429, _FRIENDLY["RATE_LIMITED"])
    client = license_client.get_client()
    try:
        return _public_status(client.renew())
    except NotActivated:
        return _error("LICENSE_NOT_ACTIVATED", 409, _FRIENDLY["LICENSE_NOT_ACTIVATED"])
    except MachineCodeUnavailable:
        return _machine_code_error()
    except LicenseServerError as e:
        return _server_error(e) if e.code == "RATE_LIMITED" else _server_error_with_state(e, client)
    except LicenseServerUnreachable:
        return _unreachable()
    except Exception:
        logger.exception("手动续租失败")
        return _unreachable()


def _server_error_with_state(e: LicenseServerError, client) -> JSONResponse:
    code = e.code if e.code in _STATUS else "LICENSE_INVALID"
    return _error(code, _STATUS[code], _FRIENDLY[code], state=client.status().get("state"))


@router.post("/deactivate")
async def deactivate():
    try:
        license_client.get_client().deactivate()
    except Exception:
        logger.exception("清除授权失败")
        return _error("LICENSE_STORE_ERROR", 500, "清除本机授权失败")
    return _public_status(license_client.get_client().status())
