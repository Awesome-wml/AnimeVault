"""semver 解析与比较。构建元数据（+xxx）解析但比较时忽略；预发布（-beta.1）按 semver 规则低于同号正式版。"""
from __future__ import annotations

import re
from typing import Tuple

_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
                 r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
                 r"(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$")

Key = Tuple


def parse(v: str) -> Key:
    """返回可直接比较的 key；格式不合法抛 ValueError。"""
    m = _RE.match(v.strip()) if isinstance(v, str) and len(v) <= 64 else None
    if not m:
        raise ValueError("版本号格式应为 x.y.z（可带 -预发布 与 +构建信息）")
    major, minor, patch, pre = int(m[1]), int(m[2]), int(m[3]), m[4]
    if pre is None:
        return (major, minor, patch, 1, ())
    ids = tuple((0, int(p), "") if p.isdigit() else (1, 0, p) for p in pre.split("."))
    return (major, minor, patch, 0, ids)


def is_valid(v: str) -> bool:
    try:
        parse(v)
        return True
    except ValueError:
        return False


def compare(a: str, b: str) -> int:
    ka, kb = parse(a), parse(b)
    return (ka > kb) - (ka < kb)
