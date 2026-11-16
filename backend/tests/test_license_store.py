"""L-27 SecureLicenseStore：加密存储、降级模式、迁移、并发、原子写。全部用内存钥匙串后端，不碰真实钥匙串。"""
import json
import os
import stat
import threading

import pytest
from keyring.backend import KeyringBackend
from keyring.backends import fail
from keyring.errors import PasswordDeleteError

from core import license_client
from core.license_client import LicenseClient, MemoryLicenseStore, FileLicenseStore
from core.license_store import (
    KeyringVault, LicenseStoreError, SecureLicenseStore, SERVICE_NAME,
)

COMPS = ["aaaaaaaaaaaaaaaa", "bbbbbbbbbbbbbbbb", "cccccccccccccccc"]
OTHER = ["1111111111111111", "2222222222222222", "3333333333333333"]


class MemKeyring(KeyringBackend):
    priority = 1

    def __init__(self):
        super().__init__()
        self.d = {}

    def get_password(self, service, username):
        return self.d.get((service, username))

    def set_password(self, service, username, password):
        self.d[(service, username)] = password

    def delete_password(self, service, username):
        if (service, username) not in self.d:
            raise PasswordDeleteError("none")
        del self.d[(service, username)]


def make_store(tmp_path, kr=None, comps=COMPS):
    kr = kr if kr is not None else MemKeyring()
    d = tmp_path / "data" / "license"
    return SecureLicenseStore(d, components_provider=lambda: list(comps), vault=KeyringVault(kr)), kr


LEASE = {"lease": "tok", "server_time": 1000, "wall_at": 1000.0, "mono_at": 5.0, "wall_max": 1000.0,
         "last_renew_ok_at": 1000, "license": {"plan": "pro"}, "block": None}


def test_roundtrip_and_permissions(tmp_path):
    s, kr = make_store(tmp_path)
    assert s.read() is None and s.read_lease() is None
    s.write("CODE-1", LEASE)
    assert s.read() == "CODE-1" and s.read_lease() == LEASE
    assert s.storage_mode == "secure"
    assert stat.S_IMODE(os.stat(s.path).st_mode) == 0o600
    raw = s.path.read_bytes()
    assert b"CODE-1" not in raw and b"tok" not in raw
    assert (SERVICE_NAME, s._account) in kr.d
    # 新实例（同一钥匙串）也读得出
    s2, _ = make_store(tmp_path, kr)
    assert s2.read() == "CODE-1"
    s.write_lease({**LEASE, "block": "suspended"})
    assert s.read() == "CODE-1" and s.read_lease()["block"] == "suspended"
    s.clear()
    assert s.read() is None and not s.path.exists()


def test_account_differs_per_data_dir(tmp_path):
    a, kr = make_store(tmp_path / "x")
    b, _ = make_store(tmp_path / "y", kr)
    assert a._account != b._account


def test_tamper_any_byte_fails(tmp_path):
    s, kr = make_store(tmp_path)
    s.write("CODE-1", LEASE)
    orig = s.path.read_bytes()
    for i in range(len(orig)):
        bad = bytearray(orig)
        bad[i] ^= 0x01
        s.path.write_bytes(bytes(bad))
        with pytest.raises(LicenseStoreError):
            s.read()
    s.path.write_bytes(orig[:-1])
    with pytest.raises(LicenseStoreError):
        s.read()
    s.path.write_bytes(orig)
    assert s.read() == "CODE-1"


def test_copied_to_other_machine_fails(tmp_path):
    s, kr = make_store(tmp_path)
    s.write("CODE-1", LEASE)
    # 同一份文件 + 同一把数据密钥（被一起拷走），但机器码分量不同
    t, _ = make_store(tmp_path, kr, comps=OTHER)
    with pytest.raises(LicenseStoreError):
        t.read()


def test_data_key_lost(tmp_path):
    s, kr = make_store(tmp_path)
    s.write("CODE-1", LEASE)
    kr.d.clear()
    s2, _ = make_store(tmp_path, kr)
    with pytest.raises(LicenseStoreError):
        s2.read()
    with pytest.raises(LicenseStoreError):
        s2.read_lease()
    # 客户端按 invalid 处理，不崩溃
    assert LicenseClient(store=s2, components_provider=lambda: list(COMPS)).status()["state"] == "invalid"
    # 重新激活（整体写入）可恢复
    s2.write("CODE-2", LEASE)
    assert s2.read() == "CODE-2"


def test_fallback_when_keychain_unavailable(tmp_path, caplog):
    s, _ = make_store(tmp_path, fail.Keyring())
    with caplog.at_level("WARNING"):
        s.write("CODE-1", LEASE)
    assert s.storage_mode == "fallback"
    assert any("降级" in r.message for r in caplog.records)
    assert "CODE-1" not in caplog.text
    assert b"CODE-1" not in s.path.read_bytes()
    assert stat.S_IMODE(os.stat(s.salt_path).st_mode) == 0o600
    s2, _ = make_store(tmp_path, fail.Keyring())
    assert s2.read() == "CODE-1" and s2.storage_mode == "fallback"
    st = LicenseClient(store=s2, components_provider=lambda: list(COMPS)).status()
    assert st["storage_mode"] == "fallback"


def test_fallback_tamper_and_cross_machine(tmp_path):
    s, _ = make_store(tmp_path, fail.Keyring())
    s.write("CODE-1", LEASE)
    orig = s.path.read_bytes()
    for i in (0, 4, 6, len(orig) // 2, len(orig) - 1):
        bad = bytearray(orig)
        bad[i] ^= 0x01
        s.path.write_bytes(bytes(bad))
        with pytest.raises(LicenseStoreError):
            s.read()
    s.path.write_bytes(orig)
    t, _ = make_store(tmp_path, fail.Keyring(), comps=OTHER)
    with pytest.raises(LicenseStoreError):
        t.read()
    s.salt_path.unlink()
    with pytest.raises(LicenseStoreError):
        s.read()


def test_no_silent_downgrade_when_secure_file_exists(tmp_path):
    s, kr = make_store(tmp_path)
    s.write("CODE-1", LEASE)
    s2, _ = make_store(tmp_path, fail.Keyring())  # 钥匙串突然不可用
    with pytest.raises(LicenseStoreError):
        s2.read()
    with pytest.raises(LicenseStoreError):
        s2.write("CODE-2", LEASE)
    assert not s2.salt_path.exists()


def test_fallback_upgrades_to_secure_when_keychain_returns(tmp_path):
    s, _ = make_store(tmp_path, fail.Keyring())
    s.write("CODE-1", LEASE)
    kr = MemKeyring()
    s2, _ = make_store(tmp_path, kr)
    s2.write_lease(LEASE)
    assert s2.storage_mode == "secure" and s2.read() == "CODE-1"


def test_migrate_legacy_plaintext(tmp_path):
    s, kr = make_store(tmp_path)
    s.dir.mkdir(parents=True)
    legacy = {"code": "OLD-CODE", "saved_at": 123,
              "lease": {**LEASE, "block": "suspended", "block_at": 99}}
    s.legacy_path.write_text(json.dumps(legacy))
    assert s.read() == "OLD-CODE"
    assert not s.legacy_path.exists()
    assert s.path.exists()
    lease = s.read_lease()
    assert lease["block"] == "suspended" and lease["wall_max"] == 1000.0
    # 重启后仍在
    s2, _ = make_store(tmp_path, kr)
    assert s2.read() == "OLD-CODE" and s2.read_lease()["block"] == "suspended"


def test_migrate_legacy_code_only(tmp_path):
    s, _ = make_store(tmp_path)
    s.dir.mkdir(parents=True)
    s.legacy_path.write_text(json.dumps({"code": "OLD", "saved_at": 1}))
    assert s.read() == "OLD" and s.read_lease() is None and not s.legacy_path.exists()


def test_migrate_via_write_lease_and_fallback(tmp_path):
    s, _ = make_store(tmp_path, fail.Keyring())
    s.dir.mkdir(parents=True)
    s.legacy_path.write_text(json.dumps({"code": "OLD", "lease": LEASE}))
    s.write_lease({**LEASE, "wall_max": 2000.0})
    assert s.read() == "OLD" and s.read_lease()["wall_max"] == 2000.0 and not s.legacy_path.exists()


def test_migration_failure_keeps_legacy(tmp_path, monkeypatch):
    s, _ = make_store(tmp_path)
    s.dir.mkdir(parents=True)
    s.legacy_path.write_text(json.dumps({"code": "OLD", "lease": LEASE}))

    def boom(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(LicenseStoreError):
        s.read()
    assert json.loads(s.legacy_path.read_text())["code"] == "OLD"
    monkeypatch.undo()
    assert s.read() == "OLD" and not s.legacy_path.exists()


def test_replanted_legacy_after_migration_is_ignored(tmp_path):
    s, kr = make_store(tmp_path)
    s.dir.mkdir(parents=True)
    s.legacy_path.write_text(json.dumps({"code": "OLD", "lease": LEASE}))
    s.read()
    s.path.unlink()  # 攻击者删掉加密文件并放回一份改过的明文
    s.legacy_path.write_text(json.dumps({"code": "OLD", "lease": {**LEASE, "wall_max": 0}}))
    assert s.read() is None and not s.legacy_path.exists()


def test_concurrent_writes_do_not_lose_updates(tmp_path):
    s, _ = make_store(tmp_path)
    s.write("CODE-1", {**LEASE, "n": 0})
    errors = []

    def worker(k):
        try:
            for _ in range(10):
                # 读-改-写必须各自原子；用不同键避免互相覆盖同一字段
                with s._locked():
                    lease = s.read_lease()
                    lease[f"k{k}"] = lease.get(f"k{k}", 0) + 1
                    s.write_lease(lease)
        except Exception as e:  # pragma: no cover
            errors.append(e)

    ts = [threading.Thread(target=worker, args=(k,)) for k in range(6)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert not errors
    lease = s.read_lease()
    assert all(lease[f"k{k}"] == 10 for k in range(6))
    assert s.read() == "CODE-1"


def test_concurrent_readers_and_writers_never_see_corruption(tmp_path):
    s, _ = make_store(tmp_path)
    s.write("CODE-1", LEASE)
    stop, errors = threading.Event(), []

    def reader():
        while not stop.is_set():
            try:
                assert s.read() == "CODE-1"
            except Exception as e:  # pragma: no cover
                errors.append(e)
                return

    rs = [threading.Thread(target=reader) for _ in range(3)]
    [t.start() for t in rs]
    for i in range(30):
        s.write_lease({**LEASE, "wall_max": float(i)})
    stop.set()
    [t.join() for t in rs]
    assert not errors


def test_touch_throttled(tmp_path):
    s, _ = make_store(tmp_path)
    now = [1000.0]
    rec = {**LEASE, "wall_at": 1000.0, "wall_max": 1000.0}
    s.write("CODE-1", rec)
    c = LicenseClient(store=s, components_provider=lambda: list(COMPS), clock=lambda: now[0])
    writes = []
    orig = s._atomic_write
    s._atomic_write = lambda t, d: (writes.append(1), orig(t, d))[1]
    for dt in (1, 10, 59):
        now[0] = 1000.0 + dt
        c.touch()
    assert writes == []
    now[0] = 1061.0
    c.touch()
    assert len(writes) == 1 and s.read_lease()["wall_max"] == 1061.0
    now[0] = 1100.0
    c.touch()
    assert len(writes) == 1


def test_atomic_write_failure_keeps_old_file(tmp_path, monkeypatch):
    s, _ = make_store(tmp_path)
    s.write("CODE-1", LEASE)
    before = s.path.read_bytes()

    def boom(*a, **k):
        raise OSError("interrupted")
    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        s.write("CODE-2", LEASE)
    monkeypatch.undo()
    assert s.path.read_bytes() == before and s.read() == "CODE-1"
    assert not list(s.dir.glob("*.tmp"))


def test_make_default_store(monkeypatch):
    monkeypatch.delenv("DONGAI_DESKTOP", raising=False)
    monkeypatch.delenv("DONGAI_LICENSE_STORE", raising=False)
    assert isinstance(license_client.make_default_store(), FileLicenseStore)
    monkeypatch.setenv("DONGAI_LICENSE_STORE", "memory")
    assert isinstance(license_client.make_default_store(), MemoryLicenseStore)
    monkeypatch.setenv("DONGAI_LICENSE_STORE", "secure")
    assert isinstance(license_client.make_default_store(), SecureLicenseStore)
    monkeypatch.setenv("DONGAI_LICENSE_STORE", "memory")
    monkeypatch.setenv("DONGAI_DESKTOP", "1")  # 桌面模式强制 secure，忽略环境变量
    assert isinstance(license_client.make_default_store(), SecureLicenseStore)
