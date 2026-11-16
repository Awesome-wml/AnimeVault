"""L-92：默认 JWT 密钥拒绝启动，及放行条件。"""
import pytest

import main
from config.settings import DEFAULT_JWT_SECRET


def _set(monkeypatch, secret, desktop=False, allow=False):
    monkeypatch.setattr(main.settings, "JWT_SECRET", secret)
    monkeypatch.delenv("DONGAI_DESKTOP", raising=False)
    monkeypatch.delenv("DONGAI_ALLOW_DEFAULT_SECRET", raising=False)
    if desktop:
        monkeypatch.setenv("DONGAI_DESKTOP", "1")
    if allow:
        monkeypatch.setenv("DONGAI_ALLOW_DEFAULT_SECRET", "1")


def test_default_secret_rejected(monkeypatch):
    _set(monkeypatch, DEFAULT_JWT_SECRET)
    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        main.check_jwt_secret()


def test_default_secret_allowed_with_flag(monkeypatch):
    _set(monkeypatch, DEFAULT_JWT_SECRET, allow=True)
    main.check_jwt_secret()


def test_default_secret_allowed_in_desktop(monkeypatch):
    _set(monkeypatch, DEFAULT_JWT_SECRET, desktop=True)
    main.check_jwt_secret()


def test_custom_secret_ok(monkeypatch):
    _set(monkeypatch, "some-random-secret")
    main.check_jwt_secret()


def test_import_does_not_check():
    # 导入 main 不应抛错（检查只在 lifespan 里）
    assert hasattr(main, "check_jwt_secret")
