"""密码哈希（hashlib.scrypt，参数写进哈希串）、JWT、登录限流。"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import time
from typing import Callable, Dict, List, Optional, Tuple

from jose import JWTError, jwt

MIN_PASSWORD_LEN = 12
_N, _R, _P, _DKLEN = 2 ** 15, 8, 1, 32
_MAXMEM = 128 * 1024 * 1024


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode("ascii")


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=_N, r=_R, p=_P, dklen=_DKLEN, maxmem=_MAXMEM)
    return f"scrypt${_N}${_R}${_P}${_b64(salt)}${_b64(dk)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt, dk = stored.split("$")
        if algo != "scrypt":
            return False
        n, r, p = int(n), int(r), int(p)
        if n > 2 ** 20:  # 防止被篡改的库记录触发超大内存
            return False
        salt_b, dk_b = base64.b64decode(salt), base64.b64decode(dk)
        got = hashlib.scrypt(password.encode("utf-8"), salt=salt_b, n=n, r=r, p=p,
                             dklen=len(dk_b), maxmem=_MAXMEM)
        return hmac.compare_digest(got, dk_b)
    except Exception:
        return False


# 用户不存在时也做一次等价计算，抹平时间差
_DUMMY_HASH = hash_password("dummy-password-not-used")


def burn_dummy(password: str) -> None:
    verify_password(password, _DUMMY_HASH)


def make_token(secret: str, admin_id: str, role: str, ttl: int, now: Optional[float] = None) -> Tuple[str, int]:
    iat = int(time.time() if now is None else now)
    exp = iat + ttl
    tok = jwt.encode({"sub": admin_id, "admin_id": admin_id, "role": role, "iat": iat, "exp": exp},
                     secret, algorithm="HS256")
    return tok, exp


def decode_token(secret: str, token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, secret, algorithms=["HS256"])
    except JWTError:
        return None


class LoginLimiter:
    """同一 用户名+IP 连续失败 max_fail 次，锁 lock_seconds。内存实现，重启清零。"""

    def __init__(self, max_fail: int = 5, lock_seconds: int = 900, clock: Callable[[], float] = time.time):
        self.max_fail, self.lock_seconds, self.clock = max_fail, lock_seconds, clock
        self._fails: Dict[Tuple[str, str], List[float]] = {}
        self._locked: Dict[Tuple[str, str], float] = {}

    def locked_for(self, key) -> int:
        until = self._locked.get(key)
        if until is None:
            return 0
        left = until - self.clock()
        if left <= 0:
            self._locked.pop(key, None)
            self._fails.pop(key, None)
            return 0
        return int(left) + 1

    def record_failure(self, key) -> bool:
        """返回本次失败是否触发了锁定。"""
        n = self._fails.get(key, [0])[0] + 1
        self._fails[key] = [n]
        if n >= self.max_fail:
            self._locked[key] = self.clock() + self.lock_seconds
            return True
        return False

    def record_success(self, key) -> None:
        self._fails.pop(key, None)
        self._locked.pop(key, None)
