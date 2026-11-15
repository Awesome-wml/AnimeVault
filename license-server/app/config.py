"""配置：全部来自环境变量，没有任何默认密钥。"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Optional

from dongai_license import crypto

_PLACEHOLDERS = {
    "changeme", "change-me", "change_me", "secret", "your-secret", "your_secret",
    "replace-me", "replace_me", "xxx", "todo", "password", "jwt-secret", "please-change",
}


class ConfigError(RuntimeError):
    """配置缺失或不合法，服务拒绝启动。"""


def _looks_placeholder(v: str) -> bool:
    low = v.strip().lower()
    return (
        low in _PLACEHOLDERS
        or low.startswith(("changeme", "change-me", "change_me", "replace", "your-", "your_", "<"))
        or len(set(low)) <= 2
    )


@dataclass(frozen=True)
class DbSettings:
    store: str = "mongo"
    mongo_url: Optional[str] = None
    mongo_db: str = "dongai_license"


@dataclass(frozen=True)
class Settings:
    db: DbSettings
    jwt_secret: str = field(repr=False)
    signing_private_key: str = field(repr=False)
    signing_public_key: str = ""
    signing_kid: str = ""
    jwt_ttl_seconds: int = 8 * 3600
    plans: tuple = ("trial", "basic", "pro", "enterprise")


def load_db_settings(env: Mapping[str, str] = os.environ) -> DbSettings:
    store = (env.get("LS_STORE") or "mongo").strip().lower()
    if store not in ("memory", "mongo"):
        raise ConfigError("LS_STORE 只能是 memory 或 mongo")
    url = (env.get("LS_MONGO_URL") or "").strip() or None
    if store == "mongo" and not url:
        raise ConfigError("LS_STORE=mongo 时必须设置 LS_MONGO_URL")
    return DbSettings(store=store, mongo_url=url,
                      mongo_db=(env.get("LS_MONGO_DB") or "dongai_license").strip())


def load_settings(env: Mapping[str, str] = os.environ) -> Settings:
    db = load_db_settings(env)
    secret = (env.get("LS_JWT_SECRET") or "").strip()
    if not secret:
        raise ConfigError("必须设置 LS_JWT_SECRET")
    if _looks_placeholder(secret) or len(secret) < 32:
        raise ConfigError("LS_JWT_SECRET 是占位符或长度不足 32，拒绝启动")
    key_file = (env.get("LS_SIGNING_PRIVATE_KEY_FILE") or "").strip()
    if not key_file:
        raise ConfigError("必须设置 LS_SIGNING_PRIVATE_KEY_FILE")
    p = Path(key_file).expanduser()
    if not p.is_file():
        raise ConfigError("签名私钥文件不存在")
    try:
        priv = p.read_text().strip()
        pub = _derive_public(priv)
    except Exception:
        # 不在错误信息里带任何私钥内容
        raise ConfigError("签名私钥文件内容无效") from None
    kid = (env.get("LS_SIGNING_KID") or "").strip() or crypto.key_id_for(pub)
    plans = tuple(x.strip() for x in (env.get("LS_PLANS") or "trial,basic,pro,enterprise").split(",") if x.strip())
    return Settings(db=db, jwt_secret=secret, signing_private_key=priv,
                    signing_public_key=pub, signing_kid=kid, plans=plans)


def _derive_public(private_b64: str) -> str:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    k = Ed25519PrivateKey.from_private_bytes(crypto.b64u_decode(private_b64))
    return crypto.b64u_encode(
        k.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw))
