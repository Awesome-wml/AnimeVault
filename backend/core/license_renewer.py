"""后台续租线程（L-41）。

- 启动时立即检查一次，之后每个 tick（默认 60 秒）检查一次是否该续租；
- 每 6 小时续租一次；租约剩余不足 12 小时、已过期、宽限中、检测到时钟回拨时立即续租；
- 网络错误/5xx/服务端异常响应：5～10 分钟（带抖动）后重试，不改变任何状态，不影响当前使用；
- 429 RATE_LIMITED：1 分钟后重试；
- 服务端明确的业务错误由 LicenseClient.renew() 先落盘状态；这里按状态决定要不要继续重试：
  suspended / expired 每小时低频重试（管理员可能恢复或延期），
  invalid / revoked / machine_mismatch / session_conflict / 服务端判定的 lease_expired 不再自动重试；
- 线程里的任何异常都被捕获并记日志（只记异常类型，不含授权码和租约），线程不会退出。
"""
from __future__ import annotations

import logging
import random
import threading
import time
from typing import Callable, Optional

from core import license_client, license_config
from core.license_client import (
    LicenseClient, LicenseServerError, LicenseServerUnreachable, NotActivated,
)

logger = logging.getLogger(__name__)

RENEW_INTERVAL_SECONDS = 6 * 3600
EARLY_RENEW_THRESHOLD_SECONDS = 12 * 3600
BACKOFF_RANGE_SECONDS = (300, 600)
RATE_LIMITED_BACKOFF_SECONDS = 60
LOW_FREQ_RETRY_SECONDS = 3600
TICK_SECONDS = 60

_NO_RETRY_STATES = frozenset({"unactivated", "invalid", "revoked", "machine_mismatch", "session_conflict"})
_LOW_FREQ_STATES = frozenset({"suspended", "expired"})


class LicenseRenewer:
    def __init__(self, client: Optional[LicenseClient] = None, *,
                 interval: float = RENEW_INTERVAL_SECONDS,
                 early_threshold: float = EARLY_RENEW_THRESHOLD_SECONDS,
                 backoff_range: tuple = BACKOFF_RANGE_SECONDS,
                 rate_limited_backoff: float = RATE_LIMITED_BACKOFF_SECONDS,
                 low_freq_retry: float = LOW_FREQ_RETRY_SECONDS,
                 tick: float = TICK_SECONDS,
                 monotonic: Callable[[], float] = time.monotonic,
                 jitter: Callable[[float, float], float] = random.uniform):
        self._client_arg = client
        self.interval, self.early_threshold = interval, early_threshold
        self.backoff_range, self.rate_limited_backoff = backoff_range, rate_limited_backoff
        self.low_freq_retry, self.tick = low_freq_retry, tick
        self._mono, self._jitter = monotonic, jitter
        self._not_before = 0.0          # 退避：此前不再尝试
        self._last_attempt: Optional[float] = None
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    @property
    def client(self) -> LicenseClient:
        return self._client_arg or license_client.get_client()

    # ---- 线程

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="license-renewer", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        t = self._thread
        if t and t.is_alive() and t is not threading.current_thread():
            t.join(timeout)
        self._thread = None

    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def _loop(self) -> None:
        delay = 0.0  # 启动时立即检查一次
        while not self._stop.wait(delay):
            self.run_once()
            delay = self.tick

    # ---- 一次检查

    def run_once(self) -> str:
        """检查并在需要时续租一次；返回结果标记（测试和日志用）。绝不抛异常。"""
        try:
            return self._run_once()
        except Exception as e:
            logger.error("授权续租检查异常：%s", type(e).__name__)
            self._not_before = self._mono() + self._jitter(*self.backoff_range)
            return "error"

    def _run_once(self) -> str:
        client = self.client
        try:
            client.touch()
        except Exception as e:
            logger.warning("记录时钟基准失败：%s", type(e).__name__)
        now = self._mono()
        if now < self._not_before:
            return "backoff"
        st = client.status()
        state = st["state"]
        if state in _NO_RETRY_STATES or (state == "lease_expired" and st.get("server_blocked")):
            return "idle"
        if state in _LOW_FREQ_STATES:
            if self._last_attempt is not None and now - self._last_attempt < self.low_freq_retry:
                return "wait"
        elif not self._due(client, st):
            return "wait"
        self._last_attempt = now
        try:
            client.renew()
        except NotActivated:
            return "not_activated"
        except LicenseServerUnreachable as e:
            self._not_before = now + self._jitter(*self.backoff_range)
            logger.warning("续租失败（%s），%d 秒内不再重试", e.reason, int(self._not_before - now))
            return "unreachable"
        except LicenseServerError as e:
            if e.code == "RATE_LIMITED":
                self._not_before = now + self.rate_limited_backoff
                return "rate_limited"
            logger.warning("续租被服务端拒绝：%s", e.code)
            return "rejected:" + e.code
        self._not_before = 0.0
        logger.info("授权续租成功")
        return "renewed"

    def _due(self, client: LicenseClient, st: dict) -> bool:
        state = st["state"]
        if state in ("grace", "lease_expired", "clock_rollback"):
            return True
        trusted = client.trusted_now()
        last_ok, lease_exp = st.get("last_renew_ok_at"), st.get("lease_expires_at")
        if trusted is None or last_ok is None or lease_exp is None:
            return True
        return trusted - last_ok >= self.interval or lease_exp - trusted < self.early_threshold


# ---------------------------------------------------------------- 进程内单例

_renewer: Optional[LicenseRenewer] = None
_lock = threading.Lock()


def get_renewer() -> LicenseRenewer:
    global _renewer
    with _lock:
        if _renewer is None:
            _renewer = LicenseRenewer()
        return _renewer


def set_renewer(renewer: Optional[LicenseRenewer]) -> None:
    global _renewer
    with _lock:
        _renewer = renewer


def start_if_enabled() -> bool:
    """应用启动时调用：桌面模式启用；非桌面模式仅 DONGAI_LICENSE_RENEW=1 时启用。"""
    if not license_config.renewer_enabled():
        return False
    get_renewer().start()
    return True


def stop() -> None:
    with _lock:
        r = _renewer
    if r is not None:
        r.stop()
