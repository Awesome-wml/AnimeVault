"""客户端授权（L-26 离线校验，L-41 在线租约）。

- 授权码由服务端私钥签名，客户端用内置公钥（core/license_keys.py）离线验证真伪与机器码分量；
- 首次激活必须联网：校验授权码后向服务端 /activate 换取租约（服务端据此绑定设备）；
- 每次 status() 都重新读取存储、重新验证授权码与租约，不缓存「通过」结果，任何异常按未授权处理（fail closed）；
- 租约过期后有 72 小时离线宽限（GRACE_SECONDS，写死在客户端，不读服务端、不受环境变量影响）；
- 时间基准以服务端 server_time 为准，并检测系统时钟回拨；
- 存储只能经 LicenseStore 接口访问（L-27 会换成系统钥匙串实现）。
- 授权到期时间、套餐、功能点一律取自**租约 payload 内的已签名字段**（lexp/plan/features/cv）；
  服务端响应 JSON 里的 license.* 不在签名内，不可信，不参与决策、也不落盘。
  授权码 payload 里的 exp/plan/features 与租约冲突时**以租约为准**（租约是服务端最新的判断，
  管理员延期/改套餐后旧授权码仍可能留在本机）；授权码只用于离线验真、机器码匹配和取 lid。

日志约定：授权码和租约原文永不进日志。
"""
from __future__ import annotations

import abc
import copy
import json
import logging
import os
import sys
import threading
import time
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import httpx

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
    LeaseExpired, LicenseError, LicenseExpired, LicenseInvalid, MachineMismatch,
)

from core import license_config, license_keys  # noqa: E402

logger = logging.getLogger(__name__)

PUBKEYS_ENV = "DONGAI_LICENSE_PUBKEYS"
DEV_ENV = "DONGAI_LICENSE_DEV"

GRACE_SECONDS = 259200          # 离线宽限 72 小时；写死，不从服务端读，不允许环境变量修改
CLOCK_TOLERANCE_SECONDS = 300   # 墙钟比上次记录早超过 5 分钟视为回拨
WALL_MAX_STEP_SECONDS = 60      # wall_max 最多每分钟落盘一次


class LicenseState(str, Enum):
    UNACTIVATED = "unactivated"            # 未激活（含老版本存储：需要联网重新激活）
    VALID = "valid"                        # 有效
    GRACE = "grace"                        # 租约已过期，离线宽限内（仍可完整使用）
    LEASE_EXPIRED = "lease_expired"        # 超出宽限，需联网（只读）
    EXPIRED = "expired"                    # 授权已到期（只读）
    SUSPENDED = "suspended"                # 授权被停用（只读）
    REVOKED = "revoked"                    # 授权被吊销（本地授权已清除）
    SESSION_CONFLICT = "session_conflict"  # 授权在另一台设备被激活，本机被顶掉
    CLOCK_ROLLBACK = "clock_rollback"      # 检测到系统时间回拨，需联网
    MACHINE_MISMATCH = "machine_mismatch"  # 机器码不匹配
    INVALID = "invalid"                    # 无效（篡改、未知密钥、存储读取失败等）


S = LicenseState
FULL_STATES = frozenset({S.VALID.value, S.GRACE.value})
READONLY_STATES = frozenset({S.EXPIRED.value, S.SUSPENDED.value, S.LEASE_EXPIRED.value})
# 服务端明确拒绝后落盘、保留授权码和租约的状态
PERSISTED_BLOCKS = frozenset({S.SUSPENDED.value, S.EXPIRED.value, S.MACHINE_MISMATCH.value,
                              S.SESSION_CONFLICT.value, S.LEASE_EXPIRED.value})
# 服务端明确拒绝后落盘、并清除本地授权码和租约的状态
CLEARING_BLOCKS = frozenset({S.INVALID.value, S.REVOKED.value})

_FRIENDLY = {
    S.UNACTIVATED: "尚未激活，请输入授权码",
    S.VALID: "授权有效",
    S.GRACE: "当前离线使用中，请尽快联网续租，否则将进入只读模式",
    S.LEASE_EXPIRED: "离线时间过长，当前为只读模式，请联网后续租",
    S.EXPIRED: "授权已到期，当前为只读模式，请联系我们续期",
    S.SUSPENDED: "授权已被停用，当前为只读模式，请联系管理员",
    S.REVOKED: "授权已被吊销，请联系我们",
    S.SESSION_CONFLICT: "该授权已在另一台设备上使用，重新激活会让对方下线",
    S.CLOCK_ROLLBACK: "检测到系统时间异常，请联网后恢复",
    S.MACHINE_MISMATCH: "这个授权码不是本机的，请使用本机机器码申请授权",
    S.INVALID: "授权码无效，请检查是否复制完整",
}
_NEEDS_REACTIVATE_MESSAGE = "需要联网重新激活，请输入授权码"

# 服务端错误码 -> 落盘状态
_ERROR_STATE = {
    "LICENSE_INVALID": S.INVALID.value,
    "LICENSE_MACHINE_MISMATCH": S.MACHINE_MISMATCH.value,
    "LICENSE_EXPIRED": S.EXPIRED.value,
    "LICENSE_SUSPENDED": S.SUSPENDED.value,
    "LICENSE_REVOKED": S.REVOKED.value,
    "LICENSE_SESSION_CONFLICT": S.SESSION_CONFLICT.value,
    "LEASE_EXPIRED": S.LEASE_EXPIRED.value,
}
SERVER_ERROR_CODES = frozenset(_ERROR_STATE) | {"RATE_LIMITED"}


class MachineCodeUnavailable(Exception):
    """无法采集到足够的硬件信息。"""


class LicenseServerUnreachable(Exception):
    """网络不通、超时、服务端 5xx 或返回了无法识别的内容。reason 只含类型信息，不含授权码/租约。"""

    def __init__(self, reason: str = ""):
        super().__init__(reason)
        self.reason = reason


class LicenseServerError(Exception):
    """服务端明确返回的业务错误 {code, message}。"""

    def __init__(self, code: str, message: str = "", status: int = 0):
        super().__init__(code)
        self.code, self.message, self.status = code, message, status


class NotActivated(Exception):
    """本机没有可续租的租约（未激活 / 老版本存储 / 授权已清除）。"""


# ---------------------------------------------------------------- 存储

class LicenseStore(abc.ABC):
    """授权存储接口：授权码 + 租约记录。业务代码只能通过它读写，不得直接碰文件。

    租约记录是一个 dict（lease、server_time、wall_at、mono_at、last_renew_ok_at、wall_max、license、block...），
    store 只负责原样存取。
    """

    @abc.abstractmethod
    def read(self) -> Optional[str]:
        """返回已保存的授权码；没有则返回 None。读取失败直接抛异常（调用方按未授权处理）。"""

    @abc.abstractmethod
    def read_lease(self) -> Optional[dict]:
        """返回租约记录；没有（含老格式文件）返回 None。读取失败抛异常。"""

    @abc.abstractmethod
    def write(self, code: Optional[str], lease: Optional[dict] = None) -> None:
        """整体替换授权码与租约记录（code 可为 None：只留租约记录里的状态标记）。"""

    @abc.abstractmethod
    def write_lease(self, lease: dict) -> None:
        """只替换租约记录，保留已保存的授权码。"""

    @abc.abstractmethod
    def clear(self) -> None: ...


class FileLicenseStore(LicenseStore):
    """<数据目录>/license/license.json，权限 600（目录 700）。路径每次从 paths 推导。
    文件格式：{"code": ..., "saved_at": ..., "lease": {...}}；老文件没有 lease。"""

    def __init__(self, path: Optional[Path] = None):
        self._path = path
        self._lock = threading.RLock()

    @property
    def path(self) -> Path:
        return self._path or paths.license_file()

    def _load(self) -> dict:
        try:
            raw = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return {}
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("license.json 格式不正确")
        return data

    def read(self) -> Optional[str]:
        with self._lock:
            code = self._load().get("code")
        if code is None:
            return None
        if not isinstance(code, str):
            raise ValueError("license.json 格式不正确")
        return code or None

    def read_lease(self) -> Optional[dict]:
        with self._lock:
            lease = self._load().get("lease")
        if lease is None:
            return None
        if not isinstance(lease, dict):
            raise ValueError("license.json 格式不正确")
        return lease

    def _dump(self, data: dict) -> None:
        f = self.path
        f.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(f.parent, 0o700)
        except OSError:
            pass
        tmp = f.with_name(f.name + ".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, f)

    def write(self, code: Optional[str], lease: Optional[dict] = None) -> None:
        data: Dict[str, Any] = {"code": code, "saved_at": int(time.time())}
        if lease is not None:
            data["lease"] = lease
        with self._lock:
            self._dump(data)

    def write_lease(self, lease: dict) -> None:
        with self._lock:
            data = self._load()
            data["lease"] = lease
            data.setdefault("saved_at", int(time.time()))
            self._dump(data)

    def clear(self) -> None:
        with self._lock:
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass


class MemoryLicenseStore(LicenseStore):
    """进程内存储（测试用）。"""

    def __init__(self):
        self._code: Optional[str] = None
        self._lease: Optional[dict] = None

    def read(self):
        return self._code

    def read_lease(self):
        return copy.deepcopy(self._lease)

    def write(self, code, lease=None):
        self._code, self._lease = code, copy.deepcopy(lease)

    def write_lease(self, lease):
        self._lease = copy.deepcopy(lease)

    def clear(self):
        self._code = self._lease = None


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

def _is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


class LicenseClient:
    def __init__(self, store: Optional[LicenseStore] = None,
                 keys_provider: Callable[[], Dict[str, str]] = get_public_keys,
                 components_provider: Callable[[], List[str]] = get_machine_components,
                 clock: Optional[Callable[[], float]] = None,
                 mono: Optional[Callable[[], float]] = None,
                 transport: Optional[httpx.BaseTransport] = None,
                 server_url_provider: Callable[[], str] = license_config.get_server_url,
                 app_version: str = license_config.APP_VERSION):
        self.store = store or FileLicenseStore()
        self._keys = keys_provider
        self._components = components_provider
        self._clock = clock          # 墙钟（可注入，测试用）
        self._mono = mono or time.monotonic
        self._transport = transport  # httpx transport（可注入，测试用）
        self._server_url = server_url_provider
        self._app_version = app_version
        self._op_lock = threading.RLock()   # 串行化 activate / renew（含网络调用）
        self._rec_lock = threading.RLock()  # 保护租约记录的读-改-写
        self._anchor: Optional[tuple] = None  # 本进程写入的 (wall_at, mono_at)；只有它对应的记录才能比较单调时钟

    # ---- 时间

    def _wall(self) -> float:
        return self._clock() if self._clock else time.time()

    def _now(self) -> Optional[float]:
        return self._clock() if self._clock else None

    def _time_base(self, rec: dict) -> tuple:
        """返回 (可信的当前时间, 是否回拨)。可信时间 = 最近一次服务端时间 + 之后经过的时间。

        - 墙钟早于记录的最大墙钟（wall_at / wall_max）超过 5 分钟 -> 回拨；
        - 记录由本进程写入时还能比较单调时钟：单调时钟走的时间比墙钟多出 5 分钟以上 -> 回拨；
        - 经过的时间取墙钟与单调时钟中较大者（系统睡眠时单调时钟可能不走，不能因此多给时间）。
        """
        w, m = self._wall(), self._mono()
        server_time, wall_at, mono_at = rec["server_time"], rec["wall_at"], rec["mono_at"]
        ref = max(wall_at, rec.get("wall_max") or wall_at)
        rollback = w < ref - CLOCK_TOLERANCE_SECONDS
        elapsed = w - wall_at
        if self._anchor is not None and self._anchor == (wall_at, mono_at):
            dm = m - mono_at
            if dm - (w - wall_at) > CLOCK_TOLERANCE_SECONDS:
                rollback = True
            elapsed = max(elapsed, dm)
        return server_time + max(elapsed, 0), rollback

    def trusted_now(self) -> Optional[float]:
        """可信当前时间（无租约记录返回 None）。续租线程用。"""
        try:
            rec = self.store.read_lease()
            if not rec or not self._rec_ok(rec):
                return None
            return self._time_base(rec)[0]
        except Exception:
            return None

    @staticmethod
    def _rec_ok(rec: dict) -> bool:
        return bool(isinstance(rec.get("lease"), str) and rec["lease"]
                    and _is_int(rec.get("server_time"))
                    and isinstance(rec.get("wall_at"), (int, float))
                    and isinstance(rec.get("mono_at"), (int, float)))

    # ---- 激活

    def activate(self, code_text: str) -> dict:
        """先离线验证授权码，再联网换租约并保存。失败抛 LicenseError 子类 / LicenseServerError /
        LicenseServerUnreachable / MachineCodeUnavailable。成功返回 status() 同形的字典。"""
        code = license_token.normalize_input(code_text)  # 非字符串抛 LicenseInvalid
        comps = self._components()
        payload = license_token.verify_license(code, self._keys(), comps, now=self._now())
        with self._op_lock:
            resp = self._post("/activate", {"license_code": code, "machine_components": comps,
                                            "app_version": self._app_version})
            rec = self._grant_record(resp, comps, lid=payload["lid"])
            with self._rec_lock:
                self.store.write(code, rec)
                self._anchor = (rec["wall_at"], rec["mono_at"])
        return self.status()

    def deactivate(self) -> None:
        with self._rec_lock:
            self.store.clear()
            self._anchor = None

    # ---- 续租

    def renew(self) -> dict:
        """用当前租约向服务端续租。成功返回新的 status()；
        服务端明确拒绝时先把状态落盘再抛 LicenseServerError；网络问题抛 LicenseServerUnreachable；
        本机没有可续租的租约抛 NotActivated。"""
        with self._op_lock:
            try:
                code = self.store.read()
                rec = self.store.read_lease()
            except Exception:
                logger.exception("读取授权存储失败")
                raise NotActivated() from None
            if not code or not rec or not self._rec_ok(rec):
                raise NotActivated()
            comps = self._components()
            try:
                old = license_token.verify_lease(rec["lease"], self._keys(), comps, now=0)
            except LicenseError:
                raise NotActivated() from None
            try:
                resp = self._post("/renew", {"lease": rec["lease"], "machine_components": comps,
                                             "app_version": self._app_version})
            except LicenseServerError as e:
                self._apply_error(e)
                raise
            new = self._grant_record(resp, comps, lid=old["lid"], sid=old["sid"])
            if new.get("cv") != old["cv"]:  # 管理员重签/延期过：无需客户端动作，只记诊断日志
                logger.info("授权码版本变化 %s -> %s", old["cv"], new.get("cv"))
            with self._rec_lock:
                self.store.write_lease(new)
                self._anchor = (new["wall_at"], new["mono_at"])
        return self.status()

    def touch(self) -> None:
        """把当前墙钟记为「已见过的最大墙钟」（供回拨检测，跨进程重启有效）。续租线程每个周期调用。"""
        with self._rec_lock:
            rec = self.store.read_lease()
            if not rec or not self._rec_ok(rec):
                return
            w = self._wall()
            if w >= (rec.get("wall_max") or rec["wall_at"]) + WALL_MAX_STEP_SECONDS:
                rec = dict(rec)
                rec["wall_max"] = w
                self.store.write_lease(rec)

    def _apply_error(self, e: LicenseServerError) -> None:
        """服务端明确拒绝：把对应状态落盘（RATE_LIMITED 不改状态）。"""
        state = _ERROR_STATE.get(e.code)
        if state is None:
            return
        with self._rec_lock:
            if state in CLEARING_BLOCKS:
                self.store.write(None, {"block": state, "block_at": self._wall()})
                self._anchor = None
                return
            rec = self.store.read_lease()
            if not rec:
                return
            rec = dict(rec)
            rec["block"], rec["block_at"] = state, self._wall()
            self.store.write_lease(rec)

    # ---- HTTP

    def _post(self, path: str, body: dict) -> dict:
        url = self._server_url()
        try:
            # 不传 verify：保持 httpx 默认的 TLS 证书校验
            with httpx.Client(base_url=url, timeout=license_config.HTTP_TIMEOUT_SECONDS,
                              transport=self._transport) as c:
                r = c.post(license_config.API_PREFIX + path, json=body)
        except Exception as e:  # 网络错误、超时、地址非法等：只记类型，不记内容
            logger.warning("授权服务请求失败：%s", type(e).__name__)
            raise LicenseServerUnreachable(type(e).__name__) from None
        if r.status_code == 200:
            try:
                data = r.json()
            except ValueError:
                raise LicenseServerUnreachable("bad_response") from None
            if not isinstance(data, dict):
                raise LicenseServerUnreachable("bad_response")
            return data
        code = message = ""
        try:
            err = r.json()
            if isinstance(err, dict):
                code = err.get("code") if isinstance(err.get("code"), str) else ""
                message = err.get("message") if isinstance(err.get("message"), str) else ""
        except ValueError:
            pass
        if code in SERVER_ERROR_CODES and r.status_code < 500:
            raise LicenseServerError(code, message, r.status_code)
        logger.warning("授权服务返回异常：HTTP %s", r.status_code)
        raise LicenseServerUnreachable(f"http_{r.status_code}")

    def _grant_record(self, resp: dict, comps: List[str], *, lid: str, sid: Optional[str] = None) -> dict:
        """校验服务端返回的租约并生成存储记录；校验不过按「服务端响应异常」处理，不改动本地状态。"""
        lease, server_time = resp.get("lease"), resp.get("server_time")
        if not isinstance(lease, str) or not _is_int(server_time):
            raise LicenseServerUnreachable("bad_response")
        try:
            lp = license_token.verify_lease(lease, self._keys(), comps, now=server_time)
        except LicenseError:
            logger.warning("服务端返回的租约校验失败")
            raise LicenseServerUnreachable("bad_lease") from None
        if lp["lid"] != lid or (sid is not None and lp["sid"] != sid):
            logger.warning("服务端返回的租约与本机授权不一致")
            raise LicenseServerUnreachable("bad_lease")
        # 响应 JSON 的 license.* 只是展示用的未签名副本：不解析进记录；plan/features/lexp 都从租约 payload 推导。
        # cv 仅作诊断记录。
        w, m = self._wall(), self._mono()
        return {"lease": lease, "server_time": server_time, "wall_at": w, "mono_at": m,
                "wall_max": w, "last_renew_ok_at": server_time, "cv": lp["cv"], "block": None}

    # ---- 状态

    def status(self) -> dict:
        """每次都重新读取并验证；任何异常都不会外泄，按无效处理（fail closed）。"""
        try:
            return self._status()
        except Exception:
            logger.exception("授权状态计算异常")
            return self._result(S.INVALID)

    def _status(self) -> dict:
        try:
            code = self.store.read()
            rec = self.store.read_lease()
        except Exception:
            logger.exception("读取授权存储失败")
            return self._result(S.INVALID)
        block = rec.get("block") if isinstance(rec, dict) else None
        if not code:
            if block in CLEARING_BLOCKS:
                return self._result(LicenseState(block), server_blocked=True)
            return self._result(S.UNACTIVATED)
        try:
            # now=0：这里只验签名和机器码，到期由租约与服务端到期时间判断
            payload = license_token.verify_license(code, self._keys(), self._components(), now=0)
        except MachineMismatch:
            return self._result(S.MACHINE_MISMATCH, rec=rec)
        except LicenseError:
            return self._result(S.INVALID, rec=rec)

        if not rec or not self._rec_ok(rec):
            # 老版本只存了授权码、没有租约：不放行，要求联网重新激活
            return self._result(S.UNACTIVATED, needs_online=True, message=_NEEDS_REACTIVATE_MESSAGE)

        if block in PERSISTED_BLOCKS:
            return self._result(LicenseState(block), payload, rec, server_blocked=True)

        trusted, rollback = self._time_base(rec)
        try:
            lp = license_token.verify_lease(rec["lease"], self._keys(), self._components(), now=trusted)
            lease_expired = False
        except LeaseExpired as e:
            lp, lease_expired = e.payload, True
        except MachineMismatch:
            return self._result(S.MACHINE_MISMATCH, payload, rec)
        except LicenseError:
            return self._result(S.INVALID, payload, rec)
        if lp["lid"] != payload["lid"]:
            return self._result(S.INVALID, payload, rec)
        if rollback:
            return self._result(S.CLOCK_ROLLBACK, payload, rec, lease_exp=lp["exp"], lease=lp)

        # 授权到期以租约内签名的 lexp 为准（不看授权码的 exp，也不看响应 JSON）
        if trusted >= lp["lexp"]:
            return self._result(S.EXPIRED, payload, rec, lease_exp=lp["exp"], lease=lp)
        if not lease_expired:
            return self._result(S.VALID, payload, rec, lease_exp=lp["exp"], lease=lp)
        grace_until = lp["exp"] + GRACE_SECONDS
        if trusted < grace_until:
            return self._result(S.GRACE, payload, rec, lease_exp=lp["exp"], grace_until=grace_until, lease=lp)
        return self._result(S.LEASE_EXPIRED, payload, rec, lease_exp=lp["exp"], lease=lp)

    # ---- 内部

    def _machine_code_or_none(self) -> Optional[str]:
        try:
            return machine_code.format_machine_code(self._components())
        except Exception:
            return None

    def _signed_lease(self, rec: Optional[dict]) -> Optional[dict]:
        """从记录里的租约取已验签的 payload（只验签名与机器码，不看过期）；验不过返回 None。"""
        try:
            if not rec or not isinstance(rec.get("lease"), str):
                return None
            return license_token.verify_lease(rec["lease"], self._keys(), self._components(), now=0)
        except Exception:
            return None

    def _result(self, state: LicenseState, payload: Optional[dict] = None, rec: Optional[dict] = None, *,
                lease: Optional[dict] = None,
                lease_exp: Optional[int] = None, grace_until: Optional[int] = None,
                needs_online: Optional[bool] = None, message: Optional[str] = None,
                server_blocked: bool = False) -> dict:
        # plan / features / expires_at 取自租约内的签名字段；没有可验的租约时才回退到授权码 payload（仅展示，
        # 此时状态一定不是 valid/grace，不参与放行决策）。
        lease = lease or self._signed_lease(rec)
        src = lease or payload
        plan = src.get("plan") if src else None
        features = list(src.get("features", [])) if src else []
        exp = (lease["lexp"] if lease else (payload.get("exp") if payload else None))
        last_ok = (rec or {}).get("last_renew_ok_at")
        if needs_online is None:
            needs_online = state.value in (S.GRACE.value, S.LEASE_EXPIRED.value, S.CLOCK_ROLLBACK.value)
        return {
            "state": state.value,
            "plan": plan,
            "features": list(features),
            "expires_at": exp,
            "grace_until": grace_until,
            "lease_expires_at": lease_exp,
            "readonly": state.value in READONLY_STATES,
            "last_renew_ok_at": last_ok if _is_int(last_ok) else None,
            "needs_online": bool(needs_online),
            "server_blocked": server_blocked,
            "machine_code": self._machine_code_or_none(),
            "message": message or _FRIENDLY[state],
        }


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
    "LicenseState", "LicenseStore", "FileLicenseStore", "MemoryLicenseStore", "LicenseClient",
    "MachineCodeUnavailable", "LicenseServerUnreachable", "LicenseServerError", "NotActivated",
    "LicenseError", "LicenseExpired", "LicenseInvalid", "MachineMismatch",
    "GRACE_SECONDS", "FULL_STATES", "READONLY_STATES",
    "get_client", "set_client", "get_public_keys", "get_machine_code", "get_machine_components",
]
