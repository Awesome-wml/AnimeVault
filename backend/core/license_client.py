"""客户端授权（L-26）：离线激活与状态校验。

- 授权码由服务端私钥签名，客户端用内置公钥（core/license_keys.py）离线验证真伪、机器码分量与有效期；
- 每次 status() 都重新读取已保存的授权码并重新验证，不缓存「通过」结果；
- 存储只能经 LicenseStore 接口访问（L-27 会换成系统钥匙串实现）。
在线续租（租约）是后续任务 L-41，这里不涉及。
"""
from __future__ import annotations

import abc
import json
import logging
import os
import sys
import threading
import time
from enum import Enum
from pathlib import Path
from typing import Callable, Dict, List, Optional

from config import paths

# ---- 共享库导入：先正常导入，失败时把仓库内 ../license 加入 sys.path 再导入 ----
try:
    import dongai_license  # noqa: F401
except ImportError:  # pragma: no cover - 取决于运行环境
    _LICENSE_LIB_DIR = paths.REPO_ROOT / "license"
    if str(_LICENSE_LIB_DIR) not in sys.path:
        sys.path.append(str(_LICENSE_LIB_DIR))
    import dongai_license  # noqa: F401

from dongai_license import license_token, machine_code  # noqa: E402
from dongai_license.license_token import (  # noqa: E402
    LicenseError, LicenseExpired, LicenseInvalid, MachineMismatch,
)

from core import license_keys  # noqa: E402

logger = logging.getLogger(__name__)

PUBKEYS_ENV = "DONGAI_LICENSE_PUBKEYS"
DEV_ENV = "DONGAI_LICENSE_DEV"


class LicenseState(str, Enum):
    UNACTIVATED = "unactivated"          # 未激活
    VALID = "valid"                      # 有效
    EXPIRED = "expired"                  # 已过期
    MACHINE_MISMATCH = "machine_mismatch"  # 机器码不匹配
    INVALID = "invalid"                  # 无效（篡改、未知密钥、存储读取失败等）


_FRIENDLY = {
    LicenseState.UNACTIVATED: "尚未激活，请输入授权码",
    LicenseState.VALID: "授权有效",
    LicenseState.EXPIRED: "授权已到期，请联系我们续期",
    LicenseState.MACHINE_MISMATCH: "这个授权码不是本机的，请使用本机机器码申请授权",
    LicenseState.INVALID: "授权码无效，请检查是否复制完整",
}


class MachineCodeUnavailable(Exception):
    """无法采集到足够的硬件信息。"""


# ---------------------------------------------------------------- 存储

class LicenseStore(abc.ABC):
    """授权码存储接口。业务代码只能通过它读写，不得直接碰文件。"""

    @abc.abstractmethod
    def read(self) -> Optional[str]:
        """返回已保存的授权码；没有则返回 None。读取失败直接抛异常（调用方按未授权处理）。"""

    @abc.abstractmethod
    def write(self, code: str) -> None: ...

    @abc.abstractmethod
    def clear(self) -> None: ...


class FileLicenseStore(LicenseStore):
    """<数据目录>/license/license.json，权限 600（目录 700）。路径每次从 paths 推导。"""

    def __init__(self, path: Optional[Path] = None):
        self._path = path

    @property
    def path(self) -> Path:
        return self._path or paths.license_file()

    def read(self) -> Optional[str]:
        try:
            raw = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        data = json.loads(raw)
        code = data.get("code") if isinstance(data, dict) else None
        if code is None:
            return None
        if not isinstance(code, str):
            raise ValueError("license.json 格式不正确")
        return code or None

    def write(self, code: str) -> None:
        f = self.path
        f.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(f.parent, 0o700)
        except OSError:
            pass
        tmp = f.with_name(f.name + ".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({"code": code, "saved_at": int(time.time())}, fh)
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, f)

    def clear(self) -> None:
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass


# ---------------------------------------------------------------- 公钥与机器码

def desktop_mode() -> bool:
    return paths.is_desktop()


def get_public_keys() -> Dict[str, str]:
    """内置公钥。仅 DONGAI_LICENSE_DEV=1 且非桌面模式才允许用环境变量覆盖；桌面模式一律忽略。"""
    if (not desktop_mode()
            and os.environ.get(DEV_ENV, "").strip() == "1"
            and os.environ.get(PUBKEYS_ENV, "").strip()):
        try:
            keys = json.loads(os.environ[PUBKEYS_ENV])
            if isinstance(keys, dict) and all(isinstance(k, str) and isinstance(v, str) for k, v in keys.items()):
                return keys
        except ValueError:
            pass
        logger.warning("DONGAI_LICENSE_PUBKEYS 格式不正确，已忽略")
    return dict(license_keys.PUBLIC_KEYS)


_components_cache: Optional[List[str]] = None
_components_fail: Optional[tuple] = None  # (截止时间, 错误信息)：采集失败后 30 秒内不重复起子进程
_components_lock = threading.Lock()
_FAIL_TTL = 30


def get_machine_components() -> List[str]:
    """本机机器码分量（成功后进程内只算一次；失败只短暂缓存）。"""
    global _components_cache, _components_fail
    with _components_lock:
        if _components_cache is None:
            if _components_fail and time.time() < _components_fail[0]:
                raise MachineCodeUnavailable(_components_fail[1])
            try:
                _components_cache = machine_code.get_components()
            except machine_code.InsufficientFingerprint as e:
                _components_fail = (time.time() + _FAIL_TTL, str(e))
                raise MachineCodeUnavailable(str(e)) from None
            _components_fail = None
        return list(_components_cache)


def get_machine_code() -> str:
    return machine_code.format_machine_code(get_machine_components())


def _reset_machine_cache() -> None:  # 测试用
    global _components_cache, _components_fail
    _components_cache = None
    _components_fail = None


# ---------------------------------------------------------------- 客户端

class LicenseClient:
    def __init__(self, store: Optional[LicenseStore] = None,
                 keys_provider: Callable[[], Dict[str, str]] = get_public_keys,
                 components_provider: Callable[[], List[str]] = get_machine_components,
                 clock: Optional[Callable[[], float]] = None):
        self.store = store or FileLicenseStore()
        self._keys = keys_provider
        self._components = components_provider
        self._clock = clock

    def _now(self) -> Optional[float]:
        return self._clock() if self._clock else None

    def _verify(self, code: str) -> dict:
        return license_token.verify_license(
            code, self._keys(), self._components(), now=self._now())

    def activate(self, code_text: str) -> dict:
        """验证并保存授权码；失败抛 LicenseError 子类。返回 status() 同形的字典。"""
        code = license_token.normalize_input(code_text)  # 非字符串抛 LicenseInvalid
        payload = self._verify(code)
        self.store.write(code)
        return self._status_from_payload(payload)

    def deactivate(self) -> None:
        self.store.clear()

    def status(self) -> dict:
        """每次都重新读取并验证；任何异常都不会外泄，按无效处理（fail closed）。"""
        try:
            code = self.store.read()
        except Exception:
            logger.exception("读取授权码失败")
            return self._result(LicenseState.INVALID)
        if not code:
            return self._result(LicenseState.UNACTIVATED)
        try:
            payload = self._verify(code)
        except LicenseExpired:
            return self._result(LicenseState.EXPIRED)
        except MachineMismatch:
            return self._result(LicenseState.MACHINE_MISMATCH)
        except LicenseError:
            return self._result(LicenseState.INVALID)
        except Exception:
            logger.exception("授权验证异常")
            return self._result(LicenseState.INVALID)
        return self._status_from_payload(payload)

    # ---- 内部

    def _machine_code_or_none(self) -> Optional[str]:
        try:
            return machine_code.format_machine_code(self._components())
        except Exception:
            return None

    def _result(self, state: LicenseState, payload: Optional[dict] = None) -> dict:
        return {
            "state": state.value,
            "plan": payload.get("plan") if payload else None,
            "features": list(payload.get("features", [])) if payload else [],
            "expires_at": payload.get("exp") if payload else None,
            "machine_code": self._machine_code_or_none(),
            "message": _FRIENDLY[state],
        }

    def _status_from_payload(self, payload: dict) -> dict:
        return self._result(LicenseState.VALID, payload)


_client: Optional[LicenseClient] = None
_client_lock = threading.Lock()


def get_client() -> LicenseClient:
    global _client
    with _client_lock:
        if _client is None:
            _client = LicenseClient()
        return _client


def set_client(client: Optional[LicenseClient]) -> None:
    """替换进程内的单例（测试用；传 None 恢复默认）。"""
    global _client
    with _client_lock:
        _client = client


__all__ = [
    "LicenseState", "LicenseStore", "FileLicenseStore", "LicenseClient", "MachineCodeUnavailable",
    "LicenseError", "LicenseExpired", "LicenseInvalid", "MachineMismatch",
    "get_client", "set_client", "get_public_keys", "get_machine_code", "get_machine_components",
]
