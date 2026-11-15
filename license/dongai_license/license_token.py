"""授权码与租约的签发/验证（L-22），格式见设计文档 4.1、6.2。

token = Base32(规范化 JSON) + "." + Base32(Ed25519 签名)
Base32 使用标准字母表，大写，去掉 "=" 填充。
"""
from __future__ import annotations

import base64
import json
import re
import time
from typing import Dict, List, Optional

from . import crypto

FORMAT_VERSION = 1
MAX_TOKEN_LEN = 4096
_B32_RE = re.compile(r"^[A-Z2-7]+$")


class LicenseError(Exception):
    code = "LICENSE_INVALID"
    default_message = "授权无效"

    def __init__(self, message: Optional[str] = None):
        super().__init__(message or self.default_message)
        self.message = message or self.default_message


class LicenseInvalid(LicenseError):
    code = "LICENSE_INVALID"
    default_message = "授权码无效"


class UnknownKey(LicenseInvalid):
    default_message = "授权码无效（签名密钥 kid 未知，请升级软件）"


class MachineMismatch(LicenseError):
    code = "LICENSE_MACHINE_MISMATCH"
    default_message = "授权与本机不匹配"


class LicenseExpired(LicenseError):
    code = "LICENSE_EXPIRED"
    default_message = "授权已到期"


class LeaseExpired(LicenseError):
    code = "LEASE_EXPIRED"
    default_message = "租约已到期，请联网续租"

    def __init__(self, message: Optional[str] = None, payload: Optional[dict] = None):
        super().__init__(message)
        self.payload = payload


# ---------- 编码 ----------

def _b32e(raw: bytes) -> str:
    return base64.b32encode(raw).decode("ascii").rstrip("=")


def _b32d(text: str) -> bytes:
    if not text or not _B32_RE.match(text):
        raise LicenseInvalid()
    try:
        return base64.b32decode(text + "=" * (-len(text) % 8))
    except Exception:
        raise LicenseInvalid() from None


def _canonical(payload: dict) -> bytes:
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _encode(private_key_b64: str, payload: dict) -> str:
    data = _canonical(payload)
    sig = crypto.sign(private_key_b64, data)
    return _b32e(data) + "." + _b32e(sig)


def _is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _is_str_list(v) -> bool:
    return isinstance(v, list) and all(isinstance(x, str) for x in v)


_LICENSE_TYPES = {
    "v": _is_int, "kid": lambda x: isinstance(x, str) and x != "",
    "lid": lambda x: isinstance(x, str) and x != "",
    "mc": _is_str_list, "plan": lambda x: isinstance(x, str),
    "features": _is_str_list, "iat": _is_int, "exp": _is_int, "dev_max": _is_int,
}
_LEASE_TYPES = {
    "v": _is_int, "kid": lambda x: isinstance(x, str) and x != "",
    "lid": lambda x: isinstance(x, str) and x != "",
    "mc": _is_str_list, "sid": lambda x: isinstance(x, str),
    "iat": _is_int, "exp": _is_int, "st": lambda x: isinstance(x, str),
}


def _parse_and_verify(token, expected_typ: str, types: dict, public_keys) -> dict:
    """解析 -> typ -> kid -> 签名，返回 payload。"""
    if not isinstance(token, str) or not token or len(token) > MAX_TOKEN_LEN:
        raise LicenseInvalid()
    parts = token.split(".")
    if len(parts) != 2:
        raise LicenseInvalid()
    data = _b32d(parts[0])
    sig = _b32d(parts[1])
    try:
        payload = json.loads(data.decode("utf-8"))
    except Exception:
        raise LicenseInvalid() from None
    if not isinstance(payload, dict):
        raise LicenseInvalid()
    if payload.get("typ") != expected_typ or payload.get("v") != FORMAT_VERSION:
        raise LicenseInvalid()
    kid = payload.get("kid")
    if not isinstance(kid, str):
        raise LicenseInvalid()
    if not isinstance(public_keys, dict) or kid not in public_keys:
        raise UnknownKey()
    if not crypto.verify(public_keys[kid], data, sig):
        raise LicenseInvalid()
    # 签名通过后再检查字段类型（防御签发端 bug）
    for key, check in types.items():
        if key not in payload or isinstance(payload[key], bool) or not check(payload[key]):
            raise LicenseInvalid()
    uid = payload.get("uid")
    if uid is not None and not isinstance(uid, str):
        raise LicenseInvalid()
    return payload


# ---------- 机器码 ----------

def components_match(a: List[str], b: List[str], min_match: int = 2) -> bool:
    """交集 >= min_match 视为同一设备；任一边分量数少于 min_match 时，
    要求较短一边的全部命中。"""
    sa, sb = set(a or []), set(b or [])
    if not sa or not sb:
        return False
    if min(len(sa), len(sb)) < min_match:
        shorter, longer = (sa, sb) if len(sa) <= len(sb) else (sb, sa)
        return shorter <= longer
    return len(sa & sb) >= min_match


def _now(now) -> float:
    return time.time() if now is None else now


# ---------- 授权码 ----------

def issue_license(private_key_b64: str, kid: str, *, lid: str, mc: List[str],
                  plan: str, features: List[str], exp: int,
                  uid: Optional[str] = None, dev_max: int = 1,
                  iat: Optional[int] = None) -> str:
    payload = {
        "typ": "license", "v": FORMAT_VERSION, "kid": kid, "lid": lid,
        "mc": list(mc), "plan": plan, "features": list(features),
        "iat": int(time.time()) if iat is None else int(iat),
        "exp": int(exp), "dev_max": int(dev_max),
    }
    if uid is not None:
        payload["uid"] = uid
    return _encode(private_key_b64, payload)


def verify_license(code: str, public_keys: Dict[str, str],
                   machine_components: List[str], *, now=None,
                   min_match: int = 2) -> dict:
    payload = _parse_and_verify(code, "license", _LICENSE_TYPES, public_keys)
    if not components_match(payload["mc"], machine_components, min_match):
        raise MachineMismatch()
    if _now(now) >= payload["exp"]:
        raise LicenseExpired()
    return payload


# ---------- 租约 ----------

def issue_lease(private_key_b64: str, kid: str, *, lid: str, mc: List[str],
                sid: str, ttl_seconds: int, st: str = "active",
                iat: Optional[int] = None) -> str:
    iat_v = int(time.time()) if iat is None else int(iat)
    payload = {
        "typ": "lease", "v": FORMAT_VERSION, "kid": kid, "lid": lid,
        "mc": list(mc), "sid": sid, "iat": iat_v,
        "exp": iat_v + int(ttl_seconds), "st": st,
    }
    return _encode(private_key_b64, payload)


def verify_lease(token: str, public_keys: Dict[str, str],
                 machine_components: List[str], *, now=None,
                 min_match: int = 2) -> dict:
    """过期时抛 LeaseExpired，其 .payload 是已验签的 payload（供宽限期逻辑）。"""
    payload = _parse_and_verify(token, "lease", _LEASE_TYPES, public_keys)
    if not components_match(payload["mc"], machine_components, min_match):
        raise MachineMismatch()
    if _now(now) >= payload["exp"]:
        raise LeaseExpired(payload=payload)
    return payload


# ---------- 展示 ----------

def format_for_display(code: str, group: int = 5, per_line: int = 8) -> str:
    """每 group 个字符一组，用短横线分隔；每行 per_line 组，换行。
    "." 分隔符保留在原位置（单独成组边界）。"""
    if group < 1 or per_line < 1:
        raise ValueError("group/per_line must be >= 1")
    body = normalize_input(code)
    chunks = [body[i:i + group] for i in range(0, len(body), group)]
    lines = ["-".join(chunks[i:i + per_line]) for i in range(0, len(chunks), per_line)]
    return "\n".join(lines)


def normalize_input(text: str) -> str:
    """去掉空白、换行、短横线、常见不可见字符，大写化。"""
    if not isinstance(text, str):
        raise LicenseInvalid()
    text = re.sub(r"[\s\-‐-―​-‍﻿]", "", text)
    return text.upper()
