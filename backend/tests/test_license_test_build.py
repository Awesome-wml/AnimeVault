"""构建期测试公钥（desktop/build_backend.py --test-public-key）的运行时行为（L-29）。
用 sys.modules 注入一个假的 core._test_build 来模拟测试构建，不依赖构建产物。"""
import importlib
import sys
import types

import pytest


@pytest.fixture
def reload_keys():
    saved = {n: sys.modules.get(n) for n in ("core._test_build", "core.license_keys", "core.license_config")}

    def _go(test_module=None):
        sys.modules.pop("core._test_build", None)
        if test_module is not None:
            sys.modules["core._test_build"] = test_module
        import core
        if hasattr(core, "_test_build"):
            delattr(core, "_test_build")
        for n in ("core.license_keys", "core.license_config"):
            sys.modules.pop(n, None)
        keys = importlib.import_module("core.license_keys")
        cfg = importlib.import_module("core.license_config")
        return keys, cfg

    yield _go
    for n, m in saved.items():
        if m is None:
            sys.modules.pop(n, None)
        else:
            sys.modules[n] = m


def test_release_build_has_no_test_marker(reload_keys):
    keys, cfg = reload_keys(None)
    assert keys.TEST_BUILD is False and keys.TEST_BUILD_MARKER == ""
    assert "testbuild" not in cfg.APP_VERSION
    assert cfg.get_server_url() == cfg.DEFAULT_SERVER_URL.rstrip("/")


def test_test_build_replaces_keys_and_marks_version(reload_keys, monkeypatch):
    monkeypatch.setenv("DONGAI_DESKTOP", "1")
    tb = types.ModuleType("core._test_build")
    tb.TEST_BUILD_MARKER = "DONGAI-TEST-BUILD-x"
    tb.PUBLIC_KEYS = {"kt": "AAAA"}
    tb.LICENSE_SERVER = "http://127.0.0.1:18100"
    keys, cfg = reload_keys(tb)
    assert keys.TEST_BUILD is True and keys.PUBLIC_KEYS == {"kt": "AAAA"}
    assert cfg.APP_VERSION.endswith("+testbuild")
    assert cfg.get_server_url() == "http://127.0.0.1:18100"  # 桌面模式也用构建时写入的地址
