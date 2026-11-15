import pytest

from app.config import ConfigError, load_settings
from app.main import create_app


def env(tmp_path, keys, **over):
    f = tmp_path / "k.key"
    f.write_text(keys[0])
    e = {"LS_STORE": "memory", "LS_JWT_SECRET": "Zk3pQ8vLm2Xn7Rb4Tw9Yc1Hd6Gs5Jf0A",
         "LS_SIGNING_PRIVATE_KEY_FILE": str(f)}
    e.update(over)
    return {k: v for k, v in e.items() if v is not None}


def test_ok_and_kid_default(tmp_path, keys):
    s = load_settings(env(tmp_path, keys))
    assert s.signing_kid == keys[2] and s.signing_public_key == keys[1]
    assert keys[0] not in repr(s)  # 私钥、密钥不进 repr/日志


def test_kid_override(tmp_path, keys):
    assert load_settings(env(tmp_path, keys, LS_SIGNING_KID="k9")).signing_kid == "k9"


@pytest.mark.parametrize("secret", [None, "", "changeme", "short", "your-secret-key-please-change-me-now", "a" * 40])
def test_bad_jwt_secret(tmp_path, keys, secret):
    with pytest.raises(ConfigError):
        load_settings(env(tmp_path, keys, LS_JWT_SECRET=secret))


def test_missing_key_file(tmp_path, keys):
    with pytest.raises(ConfigError):
        load_settings(env(tmp_path, keys, LS_SIGNING_PRIVATE_KEY_FILE=None))
    with pytest.raises(ConfigError):
        load_settings(env(tmp_path, keys, LS_SIGNING_PRIVATE_KEY_FILE=str(tmp_path / "nope")))


def test_garbage_key_error_has_no_content(tmp_path, keys):
    e = env(tmp_path, keys)
    (tmp_path / "k.key").write_text("SUPERSECRETGARBAGE")
    with pytest.raises(ConfigError) as ei:
        load_settings(e)
    assert "SUPERSECRETGARBAGE" not in str(ei.value)


def test_mongo_requires_url(tmp_path, keys):
    with pytest.raises(ConfigError):
        load_settings(env(tmp_path, keys, LS_STORE="mongo"))
    with pytest.raises(ConfigError):
        load_settings(env(tmp_path, keys, LS_STORE="bogus"))


def test_create_app_refuses_without_env(monkeypatch):
    for k in ("LS_JWT_SECRET", "LS_SIGNING_PRIVATE_KEY_FILE"):
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(ConfigError):
        create_app()
