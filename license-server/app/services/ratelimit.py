"""进程内滑动窗口限流（多进程部署时各自计数，重启清零）。"""
from __future__ import annotations

import time
from collections import deque
from typing import Callable, Deque, Dict

from ..errors import ApiError


class RateLimiter:
    def __init__(self, clock: Callable[[], float] = time.time, window: int = 60):
        self.clock, self.window = clock, window
        self._hits: Dict[str, Deque[float]] = {}

    def hit(self, key: str, limit: int) -> None:
        """记一次访问；窗口内已达 limit 次则抛 429。被拒绝的访问不计入。"""
        now = self.clock()
        q = self._hits.setdefault(key, deque())
        while q and q[0] <= now - self.window:
            q.popleft()
        if len(q) >= limit:
            raise ApiError(429, "RATE_LIMITED", "请求过于频繁，请稍后再试")
        q.append(now)
        if len(self._hits) > 20000:  # 防止无限增长：顺带清掉空闲 key
            for k in [k for k, v in self._hits.items() if not v or v[-1] <= now - self.window]:
                self._hits.pop(k, None)
