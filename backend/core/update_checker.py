"""更新检查与强制升级状态。

- 契约：GET {授权服务地址}/license/v1/update?version=&platform=&channel=
  → {"update_available": bool, "latest": {version, notes, url, sha256, size, published_at}|null,
     "force": bool, "min_supported": "x.y.z"|null}
- 授权服务地址与公钥同源（core/license_config.py）：桌面模式不认环境变量；
- 谁来调：license_renewer 的后台线程（启动后立即一次，之后每个续租周期一次），不新开线程；
  另有 POST /api/update/check 供前端「检查更新」手动触发；
- 失败静默：只记日志（异常类型，不含内容），不影响使用，保留上一次成功的结果；
- 结果缓存在内存，经 GET /api/update/status 给前端；
- 强制升级（update_required）：
    * 更新检查返回 force=true（且有更新），或本机版本低于 min_supported；
    * 授权服务对 activate/renew 返回 426 UPDATE_REQUIRED（core/license_client.py 收到时调 mark_required）。
  状态记录 {min, for_version, source}：min 有值时「当前版本 < min」即要求升级，升级后自动解除；
  min 为空时（426 没带 min_supported）在 for_version 这个版本上一直要求，换了版本自动解除。
  来源是更新检查的记录，下一次检查结果不再要求时自动清除；来源是 426 的记录只能靠升级解除。
  桌面模式落盘 <数据目录>/update_state.json，重启后立即生效；非桌面模式只存内存。
- 授权守卫（core/license_guard.py）读 is_required() 决定是否整体拦截（403 UPDATE_REQUIRED），
  本模块不碰授权状态，也不删除任何本地数据。
"""
from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urlparse

import httpx

from config import paths
from core import license_config, license_keys, version

logger = logging.getLogger(__name__)

CHECK_INTERVAL_SECONDS = 6 * 3600       # 与续租周期一致
RETRY_RANGE_SECONDS = (300, 600)        # 失败后重试间隔（带抖动）
HTTP_TIMEOUT_SECONDS = 10
SOURCE_CHECK = "update_check"
SOURCE_426 = "server_426"
UPDATE_REQUIRED_MESSAGE = "当前版本过低，请升级到新版本后继续使用"
_LATEST_FIELDS = ("version", "notes", "url", "sha256", "size", "published_at")


def download_url_allowed(url) -> bool:
    """下载地址只允许 https；开发/测试构建（或非桌面模式）额外允许 http://127.0.0.1 / localhost。"""
    if not isinstance(url, str) or not url:
        return False
    try:
        u = urlparse(url)
    except ValueError:
        return False
    if u.scheme == "https" and u.hostname:
        return True
    if u.scheme == "http" and u.hostname in ("127.0.0.1", "localhost", "::1"):
        return bool(license_keys.TEST_BUILD or not paths.is_desktop())
    return False


def _clean_latest(raw) -> Optional[dict]:
    if not isinstance(raw, dict) or not version.is_valid_version(raw.get("version")):
        return None
    out = {k: raw.get(k) for k in _LATEST_FIELDS}
    if not isinstance(out["notes"], str):
        out["notes"] = ""
    if not (isinstance(out["size"], int) and not isinstance(out["size"], bool) and out["size"] >= 0):
        out["size"] = None
    if not download_url_allowed(out["url"]):
        if out["url"]:
            logger.warning("更新地址不符合安全要求（只允许 https），已忽略")
        out["url"] = None
    sha = out["sha256"]
    out["sha256"] = sha.lower() if isinstance(sha, str) and len(sha) == 64 else None
    return out


class UpdateChecker:
    def __init__(self, *, version_provider: Callable[[], str] = version.get_version,
                 platform_provider: Callable[[], str] = version.get_platform,
                 channel_provider: Callable[[], str] = version.get_channel,
                 url_provider: Callable[[], str] = license_config.update_url,
                 transport: Optional[httpx.BaseTransport] = None,
                 clock: Callable[[], float] = time.time,
                 state_path: Optional[Path] = None,
                 persist: Optional[bool] = None):
        self._version, self._platform, self._channel = version_provider, platform_provider, channel_provider
        self._url = url_provider
        self._transport = transport
        self._clock = clock
        self._state_path = state_path
        self._persist = persist if persist is not None else (state_path is not None or paths.is_desktop())
        self._lock = threading.RLock()
        self._result: Optional[dict] = None     # 最近一次成功的检查结果（规整后）
        self._checked_at: Optional[float] = None
        self._failed = False                    # 最近一次检查是否失败
        self._required: Optional[dict] = None   # {min, for_version, source, message}
        self._loaded = False

    # ---- 当前版本

    def current_version(self) -> str:
        return self._version()

    # ---- 检查

    def check(self) -> dict:
        """联网检查一次。绝不抛异常：失败返回 snapshot 且 failed=True，保留旧结果。"""
        try:
            data = self._fetch()
        except Exception as e:
            logger.warning("更新检查失败：%s", type(e).__name__ if not isinstance(e, _CheckError) else e)
            with self._lock:
                self._failed = True
            return self.snapshot()
        with self._lock:
            self._failed = False
            self._checked_at = self._clock()
            self._result = data
            self._apply_check_result(data)
        return self.snapshot()

    def _fetch(self) -> dict:
        params = {"version": self._version(), "platform": self._platform(), "channel": self._channel()}
        try:
            with httpx.Client(timeout=HTTP_TIMEOUT_SECONDS, transport=self._transport) as c:
                r = c.get(self._url(), params=params)
        except Exception as e:
            raise _CheckError(f"network:{type(e).__name__}") from None
        if r.status_code != 200:
            raise _CheckError(f"http_{r.status_code}")
        try:
            body = r.json()
        except ValueError:
            raise _CheckError("bad_json") from None
        if not isinstance(body, dict) or not isinstance(body.get("update_available"), bool):
            raise _CheckError("bad_response")
        latest = _clean_latest(body.get("latest"))
        ms = body.get("min_supported")
        min_supported = ms if isinstance(ms, str) and version.is_valid_version(ms) else None
        update_available = bool(body["update_available"] and latest)
        force = bool(body.get("force") is True and update_available)
        return {"update_available": update_available, "latest": latest if update_available else None,
                "force": force, "min_supported": min_supported}

    def _apply_check_result(self, data: dict) -> None:
        cur = self._version()
        min_supported = data["min_supported"]
        required_min = None
        try:
            if data["force"] and data["latest"]:
                required_min = data["latest"]["version"]
            elif min_supported and version.compare_versions(cur, min_supported) < 0:
                required_min = min_supported
        except ValueError:
            required_min = None
        if required_min:
            self._set_required(required_min, UPDATE_REQUIRED_MESSAGE, SOURCE_CHECK)
        elif self._required and self._required.get("source") == SOURCE_CHECK:
            self._set_required(None, "", None)   # 服务端已不再要求

    # ---- 强制升级状态

    def mark_required(self, min_supported: str = "", message: str = "", source: str = SOURCE_426) -> None:
        with self._lock:
            ms = min_supported if version.is_valid_version(min_supported) else ""
            self._set_required(ms or None, message or UPDATE_REQUIRED_MESSAGE, source)

    def _set_required(self, min_version: Optional[str], message: str, source: Optional[str]) -> None:
        with self._lock:
            self._load()
            if source is None:
                self._required = None
            else:
                self._required = {"min": min_version, "for_version": self._version(), "source": source,
                                  "message": message or UPDATE_REQUIRED_MESSAGE}
            self._save()

    def required_info(self) -> Optional[dict]:
        """当前仍有效的强制升级信息 {min_supported, message, source}；不需要升级返回 None。"""
        with self._lock:
            self._load()
            rec = self._required
            if not rec:
                return None
            cur = self._version()
            try:
                if rec.get("min"):
                    if version.compare_versions(cur, rec["min"]) >= 0:
                        return None          # 已升级到要求的版本
                elif rec.get("for_version") != cur:
                    return None              # 没带最低版本的 426：换了版本就解除
            except ValueError:
                return None
            return {"min_supported": rec.get("min"), "message": rec.get("message") or UPDATE_REQUIRED_MESSAGE,
                    "source": rec.get("source")}

    def is_required(self) -> bool:
        try:
            return self.required_info() is not None
        except Exception:
            logger.exception("读取强制升级状态失败")
            return False

    # ---- 落盘

    def _file(self) -> Path:
        return self._state_path or (paths.data_dir() / "update_state.json")

    def _load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        if not self._persist:
            return
        try:
            data = json.loads(self._file().read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("required"), dict):
                self._required = data["required"]
        except FileNotFoundError:
            pass
        except Exception:
            logger.warning("更新状态文件读取失败，已忽略")

    def _save(self) -> None:
        if not self._persist:
            return
        try:
            f = self._file()
            f.parent.mkdir(parents=True, exist_ok=True)
            tmp = f.with_name(f.name + ".tmp")
            tmp.write_text(json.dumps({"required": self._required}, ensure_ascii=False), encoding="utf-8")
            tmp.replace(f)
        except Exception:
            logger.warning("更新状态文件写入失败")

    # ---- 给前端

    def snapshot(self) -> dict:
        with self._lock:
            res = self._result or {}
            req = self.required_info()
            return {
                "current_version": self._version(),
                "platform": self._platform(),
                "channel": self._channel(),
                "update_available": bool(res.get("update_available")),
                "latest": res.get("latest"),
                "force": bool(res.get("force")),
                "min_supported": (req or {}).get("min_supported") or res.get("min_supported"),
                "update_required": req is not None,
                "required_message": (req or {}).get("message"),
                "checked_at": int(self._checked_at) if self._checked_at else None,
                "check_failed": self._failed,
                "test_build": bool(license_keys.TEST_BUILD),   # 桌面外壳据此决定是否允许 http://127.0.0.1 下载地址
            }


class _CheckError(Exception):
    pass


_checker: Optional[UpdateChecker] = None
_lock = threading.Lock()


def get_checker() -> UpdateChecker:
    global _checker
    with _lock:
        if _checker is None:
            _checker = UpdateChecker()
        return _checker


def set_checker(checker: Optional[UpdateChecker]) -> None:
    """替换进程内单例（测试用；传 None 恢复默认）。"""
    global _checker
    with _lock:
        _checker = checker
