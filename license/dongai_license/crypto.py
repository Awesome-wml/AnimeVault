"""Ed25519 密钥与签名封装（L-21）。

密钥一律用原始 32 字节的 base64url（无填充）表示。
"""
from __future__ import annotations

import base64
import hashlib
from typing import Tuple

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)


def b64u_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def b64u_decode(text: str) -> bytes:
    if not isinstance(text, str):
        raise ValueError("not a string")
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def generate_keypair() -> Tuple[str, str]:
    """返回 (private_key_b64, public_key_b64)。"""
    priv = Ed25519PrivateKey.generate()
    priv_raw = priv.private_bytes(
        serialization.Encoding.Raw,
        serialization.PrivateFormat.Raw,
        serialization.NoEncryption(),
    )
    pub_raw = priv.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    return b64u_encode(priv_raw), b64u_encode(pub_raw)


def key_id_for(public_key_b64: str) -> str:
    """公钥 SHA-256 的前 4 字节十六进制（8 个字符），作为默认 kid。"""
    return hashlib.sha256(b64u_decode(public_key_b64)).digest()[:4].hex()


def sign(private_key_b64: str, data: bytes) -> bytes:
    priv = Ed25519PrivateKey.from_private_bytes(b64u_decode(private_key_b64))
    return priv.sign(data)


def verify(public_key_b64: str, data: bytes, sig: bytes) -> bool:
    """验证签名；任何异常都返回 False，不抛。"""
    try:
        pub = Ed25519PublicKey.from_public_bytes(b64u_decode(public_key_b64))
        pub.verify(sig, data)
        return True
    except Exception:
        return False
