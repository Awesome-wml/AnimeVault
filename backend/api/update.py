"""更新检查接口：属于授权白名单（/api/update/*），授权未激活、需要升级时也能访问。"""
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from api.license import _SlidingLimiter
from core import update_checker

router = APIRouter(prefix="/api/update", tags=["更新"])

CHECK_LIMIT = 3          # 手动检查：每分钟最多 3 次
CHECK_WINDOW = 60.0
_check_limiter = _SlidingLimiter(CHECK_LIMIT, CHECK_WINDOW)


@router.get("/status")
async def status():
    """当前版本 + 最近一次检查的缓存结果（不联网）。"""
    return update_checker.get_checker().snapshot()


# 会联网（最长 10 秒），用同步函数放线程池
@router.post("/check")
def check_now():
    if not _check_limiter.allow():
        msg = "操作太频繁，请稍后再试"
        return JSONResponse(status_code=429, content={"code": "RATE_LIMITED", "message": msg, "detail": msg})
    return update_checker.get_checker().check()
