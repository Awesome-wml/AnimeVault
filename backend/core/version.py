"""应用版本、平台、渠道（单一来源：仓库根 VERSION，见 docs/versioning.md）。

- 版本：正式版 x.y.z（semver）；测试构建（desktop/build_backend.py --test-public-key）在后面加 +testbuild；
- 打包产物里没有 VERSION 文件：构建脚本在编译前生成 core/_build_meta.py（已 gitignore，编译后删除），
  里面写死 VERSION / PLATFORM / CHANNEL；源码运行时读仓库根 VERSION，平台按本机探测，渠道默认 stable；
- platform 取值：mac-arm64 | mac-x64 | win-x64（其余平台返回 linux-x64 等，仅开发环境会遇到）；
- 版本比较 compare_versions 按 semver 优先级（忽略 +build 元数据，预发布版本小于同号正式版）。
"""
from __future__ import annotations

import platform as _platform
import re
import sys
from pathlib import Path
from typing import Optional, Tuple

from config import paths
from core import license_keys

try:
    from core import _build_meta as _bm  # type: ignore[attr-defined]
except ImportError:
    _bm = None

TEST_SUFFIX = "+testbuild"
DEFAULT_CHANNEL = "stable"
FALLBACK_VERSION = "0.0.0"
PLATFORMS = ("mac-arm64", "mac-x64", "win-x64")

_SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?(?:\+([0-9A-Za-z.-]+))?$")
_CHANNEL = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")


def parse_version(v: str) -> Tuple[int, int, int, Tuple[str, ...]]:
    """解析 semver，返回 (major, minor, patch, prerelease 标识列表)；格式不对抛 ValueError。"""
    if not isinstance(v, str):
        raise ValueError("版本号必须是字符串")
    m = _SEMVER.match(v.strip())
    if not m:
        raise ValueError(f"不是合法的 semver：{v!r}")
    pre = tuple(m.group(4).split(".")) if m.group(4) else ()
    return int(m.group(1)), int(m.group(2)), int(m.group(3)), pre


def _cmp_pre(a: Tuple[str, ...], b: Tuple[str, ...]) -> int:
    if not a and not b:
        return 0
    if not a:
        return 1   # 正式版 > 预发布
    if not b:
        return -1
    for x, y in zip(a, b):
        xn, yn = x.isdigit(), y.isdigit()
        if xn and yn:
            if int(x) != int(y):
                return -1 if int(x) < int(y) else 1
        elif xn != yn:
            return -1 if xn else 1   # 数字标识 < 字母标识
        elif x != y:
            return -1 if x < y else 1
    return (len(a) > len(b)) - (len(a) < len(b))


def compare_versions(a: str, b: str) -> int:
    """a < b 返回 -1，相等 0，a > b 返回 1；任一不合法抛 ValueError。+build 元数据不参与比较。"""
    pa, pb = parse_version(a), parse_version(b)
    if pa[:3] != pb[:3]:
        return -1 if pa[:3] < pb[:3] else 1
    return _cmp_pre(pa[3], pb[3])


def is_valid_version(v) -> bool:
    try:
        parse_version(v)
        return True
    except ValueError:
        return False


def read_version_file(path: Optional[Path] = None) -> str:
    f = path or (paths.REPO_ROOT / "VERSION")
    try:
        text = f.read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    return text.splitlines()[0].strip() if text else ""


def base_version() -> str:
    """不带 +testbuild 的版本号。"""
    v = getattr(_bm, "VERSION", "") if _bm is not None else ""
    if not v:
        v = read_version_file()
    if not is_valid_version(v):
        return FALLBACK_VERSION
    return v.split("+", 1)[0]


def get_version() -> str:
    """上报给服务端、展示给用户的版本号；测试构建带 +testbuild。"""
    v = base_version()
    return v + TEST_SUFFIX if license_keys.TEST_BUILD else v


def detect_platform() -> str:
    machine = _platform.machine().lower()
    if sys.platform == "darwin":
        return "mac-arm64" if machine in ("arm64", "aarch64") else "mac-x64"
    if sys.platform == "win32":
        return "win-x64"
    return "linux-x64"


def get_platform() -> str:
    p = getattr(_bm, "PLATFORM", "") if _bm is not None else ""
    return p or detect_platform()


def get_channel() -> str:
    c = getattr(_bm, "CHANNEL", "") if _bm is not None else ""
    return c if c and _CHANNEL.match(c) else DEFAULT_CHANNEL


def describe() -> dict:
    return {"version": get_version(), "platform": get_platform(), "channel": get_channel()}
