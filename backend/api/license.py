"""授权接口（L-26）：不需要登录，也不被全局授权拦截。"""
import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from core import license_client
from core.license_client import (
    LicenseError, LicenseExpired, LicenseInvalid, MachineMismatch, MachineCodeUnavailable,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/license", tags=["授权"])

_FRIENDLY = {
    "LICENSE_INVALID": "授权码无效，请检查是否复制完整",
    "LICENSE_MACHINE_MISMATCH": "这个授权码不是本机的，请使用本机机器码申请授权",
    "LICENSE_EXPIRED": "授权码已过期，请联系我们续期",
}
_STATUS = {"LICENSE_INVALID": 400, "LICENSE_MACHINE_MISMATCH": 403, "LICENSE_EXPIRED": 403}


class ActivateBody(BaseModel):
    code: str = ""


def _error(code: str, status: int, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"code": code, "message": message, "detail": message})


def _machine_code_error() -> JSONResponse:
    return _error("MACHINE_CODE_UNAVAILABLE", 503, "无法读取本机硬件信息，请联系我们")


@router.get("/machine-code")
async def machine_code():
    try:
        code = license_client.get_machine_code()
    except MachineCodeUnavailable:
        return _machine_code_error()
    return {"machine_code": code, "groups": code.split("-")}


@router.get("/status")
async def status():
    return license_client.get_client().status()


@router.post("/activate")
async def activate(body: ActivateBody):
    try:
        return license_client.get_client().activate(body.code)
    except MachineCodeUnavailable:
        return _machine_code_error()
    except (LicenseInvalid, LicenseExpired, MachineMismatch) as e:
        # 只用错误类型，不外泄内部细节（如 kid 未知）
        return _error(e.code, _STATUS[e.code], _FRIENDLY[e.code])
    except LicenseError:
        return _error("LICENSE_INVALID", 400, _FRIENDLY["LICENSE_INVALID"])
    except Exception:
        logger.exception("激活失败")
        return _error("LICENSE_INVALID", 400, _FRIENDLY["LICENSE_INVALID"])


@router.post("/deactivate")
async def deactivate():
    try:
        license_client.get_client().deactivate()
    except Exception:
        logger.exception("清除授权失败")
        return _error("LICENSE_STORE_ERROR", 500, "清除本机授权失败")
    return license_client.get_client().status()
