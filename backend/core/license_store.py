"""L-27 授权存储加固：SecureLicenseStore。

整份状态（授权码、租约、server_time、wall_at、wall_max、各状态标记）序列化后用 AES-256-GCM 加密并认证，
落到 <数据目录>/license/license.enc。数据密钥放系统安全存储（keyring：macOS Keychain、Windows 凭据管理器、
Linux Secret Service）。AAD 绑定本机机器码分量（排序后的哈希），文件拷到别的机器解不开。

系统安全存储不可用时不降级为明文：数据密钥改由「机器码分量 + 数据目录随机盐文件」经 HKDF 派生（强度较低，
仍能防直接编辑和跨机拷贝），storage_mode 为 "fallback"。

边界：这只是提高篡改与拷贝的成本，防不住有管理员权限、调试器、能读进程内存或替换二进制的人；
真正的防线是服务端租约签名与机器码绑定。日志里不出现授权码、租约或密钥。
"""
from __future__ import annotations

import base64
import contextlib
import hashlib
import json
import logging
import os
import secrets
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from config import paths
from core.license_client import LicenseStore, get_machine_components

try:  # 进程间文件锁（Windows 无 fcntl，退化为进程内锁）
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None

logger = logging.getLogger(__name__)

SERVICE_NAME = "DongAI"
MAGIC = b"DAL1"
MODE_SECURE, MODE_FALLBACK = 1, 2
_MODE_NAME = {MODE_SECURE: "secure", MODE_FALLBACK: "fallback"}
NONCE_LEN = 12
HEADER_LEN = len(MAGIC) + 1 + NONCE_LEN
_FALLBACK_INFO = b"DongAI-license-fallback-v1"


class LicenseStoreError(Exception):
    """存储损坏、被篡改、密钥丢失或无法读写。调用方按未授权处理（fail closed）。"""


class KeystoreUnavailable(Exception):
    """系统安全存储不可用（无后端、无头环境、用户拒绝授权等）。"""


class KeyringVault:
    """对 keyring 的薄封装：把一切后端异常统一成 KeystoreUnavailable。"""

    def __init__(self, backend=None, service: str = SERVICE_NAME):
        self._backend = backend
        self._service = service

    def _kr(self):
        if self._backend is not None:
            return self._backend
        import sys
        import keyring
        # 显式选后端，不依赖 entry point 发现（Nuitka 打包下 entry point 元数据不一定在）
        if sys.platform == "darwin":
            from keyring.backends import macOS
            self._backend = macOS.Keyring()
        elif sys.platform.startswith("win"):
            from keyring.backends import Windows
            self._backend = Windows.WinVaultKeyring()
        else:
            from keyring.backends import fail
            kr = keyring.get_keyring()
            if isinstance(kr, fail.Keyring) or getattr(kr, "priority", 1) <= 0:
                raise KeystoreUnavailable("no secret service")
            self._backend = kr
        return self._backend

    def get(self, account: str) -> Optional[str]:
        try:
            return self._kr().get_password(self._service, account)
        except KeystoreUnavailable:
            raise
        except Exception as e:
            raise KeystoreUnavailable(type(e).__name__) from None

    def set(self, account: str, value: str) -> None:
        try:
            self._kr().set_password(self._service, account, value)
        except KeystoreUnavailable:
            raise
        except Exception as e:
            raise KeystoreUnavailable(type(e).__name__) from None

    def delete(self, account: str) -> None:
        try:
            self._kr().delete_password(self._service, account)
        except KeystoreUnavailable:
            raise
        except Exception as e:
            if type(e).__name__ == "PasswordDeleteError":  # 本来就没有
                return
            raise KeystoreUnavailable(type(e).__name__) from None


def _components_digest(comps: List[str]) -> bytes:
    return hashlib.sha256("|".join(sorted(comps)).encode("utf-8")).digest()


def _secure_unlink(p: Path) -> None:
    """覆盖后删除（尽力而为；SSD / 日志文件系统上不保证物理擦除）。"""
    try:
        size = p.stat().st_size
        with open(p, "r+b") as fh:
            fh.write(b"\0" * size)
            fh.flush()
            os.fsync(fh.fileno())
    except OSError:
        pass
    try:
        p.unlink()
    except FileNotFoundError:
        pass


class SecureLicenseStore(LicenseStore):
    def __init__(self, directory: Optional[Path] = None, *,
                 components_provider: Callable[[], List[str]] = get_machine_components,
                 vault: Optional[KeyringVault] = None):
        self._dir = directory
        self._components = components_provider
        self._vault = vault or KeyringVault()
        self._lock = threading.RLock()
        self._depth = 0
        self._lock_fd: Optional[int] = None
        self._mode: Optional[int] = None  # 最近一次读/写看到的模式

    # ---- 路径与账户

    @property
    def dir(self) -> Path:
        return self._dir or paths.license_file().parent

    @property
    def path(self) -> Path:
        return self.dir / "license.enc"

    @property
    def legacy_path(self) -> Path:
        return self.dir / "license.json"

    @property
    def salt_path(self) -> Path:
        return self.dir / "store.salt"

    @property
    def _account(self) -> str:
        h = hashlib.sha256(str(self.dir.resolve().parent).encode("utf-8")).hexdigest()[:12]
        return f"license-{h}"

    @property
    def _marker_account(self) -> str:
        return self._account + "-migrated"

    @property
    def storage_mode(self) -> Optional[str]:
        """"secure" / "fallback"；还没有存储文件时按系统安全存储是否可用推断。"""
        if self._mode:
            return _MODE_NAME[self._mode]
        try:
            self._vault.get(self._account)
            return "secure"
        except KeystoreUnavailable:
            return "fallback"

    # ---- 锁

    @contextlib.contextmanager
    def _locked(self):
        with self._lock:
            if self._depth == 0 and fcntl is not None:
                try:
                    self.dir.mkdir(parents=True, exist_ok=True)
                    self._lock_fd = os.open(self.dir / "license.lock", os.O_RDWR | os.O_CREAT, 0o600)
                    fcntl.flock(self._lock_fd, fcntl.LOCK_EX)
                except OSError:
                    self._close_lock()
            self._depth += 1
            try:
                yield
            finally:
                self._depth -= 1
                if self._depth == 0:
                    self._close_lock()

    def _close_lock(self) -> None:
        if self._lock_fd is not None:
            try:
                os.close(self._lock_fd)  # 关闭即释放 flock
            except OSError:
                pass
            self._lock_fd = None

    # ---- 密钥

    def _aad(self) -> bytes:
        return b"DongAI-license-v1|" + _components_digest(self._components())

    def _fallback_key(self, create: bool) -> bytes:
        salt = None
        try:
            salt = self.salt_path.read_bytes()
        except FileNotFoundError:
            if not create:
                raise LicenseStoreError("缺少盐文件") from None
        if salt is not None and len(salt) != 32:
            raise LicenseStoreError("盐文件损坏")
        if salt is None:
            salt = secrets.token_bytes(32)
            self._atomic_write(self.salt_path, salt)
        ikm = "|".join(sorted(self._components())).encode("utf-8")
        return HKDF(algorithm=hashes.SHA256(), length=32, salt=salt, info=_FALLBACK_INFO).derive(ikm)

    def _key_for_read(self, mode: int) -> bytes:
        if mode == MODE_SECURE:
            try:
                raw = self._vault.get(self._account)
            except KeystoreUnavailable:
                raise LicenseStoreError("系统安全存储不可用，无法读取数据密钥") from None
            if not raw:
                raise LicenseStoreError("数据密钥丢失")
            try:
                key = base64.b64decode(raw, validate=True)
            except ValueError:
                raise LicenseStoreError("数据密钥格式不正确") from None
            if len(key) != 32:
                raise LicenseStoreError("数据密钥格式不正确")
            return key
        return self._fallback_key(create=False)

    def _key_for_write(self, existing_mode: Optional[int]) -> tuple:
        """返回 (mode, key)。已有安全模式文件时不允许悄悄降级。"""
        try:
            raw = self._vault.get(self._account)
            key = None
            if raw:
                try:
                    key = base64.b64decode(raw, validate=True)
                except ValueError:
                    key = None
                if key is not None and len(key) != 32:
                    key = None
            if key is None:
                key = AESGCM.generate_key(256)
                self._vault.set(self._account, base64.b64encode(key).decode("ascii"))
            return MODE_SECURE, key
        except KeystoreUnavailable:
            if existing_mode == MODE_SECURE:
                raise LicenseStoreError("系统安全存储不可用，拒绝降级写入") from None
            logger.warning("系统安全存储不可用，授权存储使用降级加密模式")
            return MODE_FALLBACK, self._fallback_key(create=True)

    # ---- 文件读写

    def _atomic_write(self, target: Path, data: bytes) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(target.parent, 0o700)
        except OSError:
            pass
        tmp = target.with_name(target.name + ".tmp")
        try:
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())
            try:
                os.chmod(tmp, 0o600)
            except OSError:
                pass
            os.replace(tmp, target)
        except BaseException:
            try:
                tmp.unlink()
            except OSError:
                pass
            raise

    def _file_mode(self) -> Optional[int]:
        try:
            with open(self.path, "rb") as fh:
                head = fh.read(len(MAGIC) + 1)
        except FileNotFoundError:
            return None
        if len(head) == len(MAGIC) + 1 and head[:4] == MAGIC and head[4] in _MODE_NAME:
            return head[4]
        return None

    def _decrypt(self, blob: bytes) -> dict:
        if len(blob) < HEADER_LEN + 16 or blob[:4] != MAGIC or blob[4] not in _MODE_NAME:
            raise LicenseStoreError("授权存储格式不正确")
        mode, nonce, ct = blob[4], blob[5:HEADER_LEN], blob[HEADER_LEN:]
        key = self._key_for_read(mode)
        try:
            plain = AESGCM(key).decrypt(nonce, ct, self._aad() + bytes([mode]))
        except InvalidTag:
            raise LicenseStoreError("授权存储认证失败（被修改或来自其他机器）") from None
        try:
            data = json.loads(plain.decode("utf-8"))
        except ValueError:
            raise LicenseStoreError("授权存储内容损坏") from None
        if not isinstance(data, dict):
            raise LicenseStoreError("授权存储内容损坏")
        self._mode = mode
        return data

    def _encrypt(self, data: dict, existing_mode: Optional[int]) -> bytes:
        mode, key = self._key_for_write(existing_mode)
        nonce = secrets.token_bytes(NONCE_LEN)
        data = dict(data)
        data["storage_mode"] = _MODE_NAME[mode]
        ct = AESGCM(key).encrypt(nonce, json.dumps(data).encode("utf-8"), self._aad() + bytes([mode]))
        self._mode = mode
        return MAGIC + bytes([mode]) + nonce + ct

    def _save(self, data: dict) -> None:
        blob = self._encrypt(data, self._file_mode())
        self._atomic_write(self.path, blob)

    def _load(self) -> dict:
        try:
            blob = self.path.read_bytes()
        except FileNotFoundError:
            return self._migrate_legacy()
        self._drop_stale_legacy()
        return self._decrypt(blob)

    # ---- 迁移

    def _migrated_marker(self) -> bool:
        try:
            return self._vault.get(self._marker_account) == "1"
        except KeystoreUnavailable:
            return False

    def _drop_stale_legacy(self) -> None:
        if self.legacy_path.exists():
            logger.info("授权存储已是加密格式，清除遗留的旧明文文件")
            _secure_unlink(self.legacy_path)

    def _migrate_legacy(self) -> dict:
        """没有加密文件时：若有旧版明文 license.json，导入并加密，成功后覆盖删除旧文件。"""
        if not self.legacy_path.exists():
            return {}
        if self._migrated_marker():
            # 已迁移过，旧文件是后来被放回来的（可能被改过），不信任
            logger.warning("忽略已迁移过的旧明文授权文件")
            _secure_unlink(self.legacy_path)
            return {}
        try:
            old = json.loads(self.legacy_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise LicenseStoreError("旧授权文件无法读取") from None
        if not isinstance(old, dict):
            raise LicenseStoreError("旧授权文件格式不正确")
        data: Dict[str, Any] = {"code": old.get("code"), "saved_at": old.get("saved_at") or int(time.time())}
        if old.get("lease") is not None:
            data["lease"] = old["lease"]
        try:
            self._save(data)
            self._decrypt(self.path.read_bytes())  # 读回确认能解开，再删旧文件
        except Exception:
            logger.warning("旧授权文件迁移失败，保留旧文件，下次再试")
            raise LicenseStoreError("旧授权文件迁移失败") from None
        if self._mode == MODE_SECURE:
            try:
                self._vault.set(self._marker_account, "1")
            except KeystoreUnavailable:
                pass
        _secure_unlink(self.legacy_path)
        logger.info("旧版明文授权文件已迁移为加密存储")
        return self._load_decrypted_copy(data)

    def _load_decrypted_copy(self, data: dict) -> dict:
        return dict(data, storage_mode=_MODE_NAME[self._mode])

    # ---- LicenseStore 接口

    def read(self) -> Optional[str]:
        with self._locked():
            code = self._load().get("code")
        if code is None:
            return None
        if not isinstance(code, str):
            raise LicenseStoreError("授权存储格式不正确")
        return code or None

    def read_lease(self) -> Optional[dict]:
        with self._locked():
            lease = self._load().get("lease")
        if lease is None:
            return None
        if not isinstance(lease, dict):
            raise LicenseStoreError("授权存储格式不正确")
        return lease

    def write(self, code: Optional[str], lease: Optional[dict] = None) -> None:
        data: Dict[str, Any] = {"code": code, "saved_at": int(time.time())}
        if lease is not None:
            data["lease"] = lease
        with self._locked():
            self._save(data)
            if self.legacy_path.exists():
                _secure_unlink(self.legacy_path)

    def write_lease(self, lease: dict) -> None:
        with self._locked():
            data = self._load()
            data["lease"] = lease
            data.setdefault("saved_at", int(time.time()))
            data.pop("storage_mode", None)
            self._save(data)

    def clear(self) -> None:
        with self._locked():
            for p in (self.path, self.legacy_path):
                if p.exists():
                    _secure_unlink(p)
            try:
                self._vault.delete(self._account)
            except KeystoreUnavailable:
                pass
            self._mode = None


__all__ = ["SecureLicenseStore", "KeyringVault", "LicenseStoreError", "KeystoreUnavailable", "SERVICE_NAME"]
