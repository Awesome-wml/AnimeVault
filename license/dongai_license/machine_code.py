"""机器码模块（L-20）：采集本机硬件标识 -> HMAC 分量 -> Base32 机器码。

原始序列号只在内存中短暂存在，不写日志、不落盘、不出现在返回值之外。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import platform
import re
import subprocess
import sys

try:  # 仅 Windows 可用
    import winreg  # type: ignore
except ImportError:  # pragma: no cover
    winreg = None  # type: ignore

PRODUCT_SALT: bytes = b"dongai-mc-v1"
COMPONENT_BYTES = 8
MAX_COMPONENTS = 9
_B32 = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"
_CMD_TIMEOUT = 5

_PLACEHOLDERS = {
    "", "none", "unknown", "null", "n/a", "na", "default", "defaultstring",
    "tobefilledbyo.e.m.", "tobefilledbyoem", "systemserialnumber", "notspecified",
    "notapplicable", "systemproductname", "baseboardserialnumber", "oem",
    "chassisserialnumber", "notavailable", "invalid", "0123456789", "123456789",
}


class InsufficientFingerprint(Exception):
    """有效硬件来源不足 2 个，无法生成可靠机器码。"""


# ---------------------------------------------------------------- 采集

def _default_runner(cmd: list[str]) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=_CMD_TIMEOUT,
                           stdin=subprocess.DEVNULL, errors="ignore")
    except Exception:
        return ""
    return r.stdout if r.returncode == 0 else ""


def _safe(runner, cmd: list[str]) -> str:
    try:
        return runner(cmd) or ""
    except Exception:
        return ""


def _first_nonempty(*vals: str) -> str:
    for v in vals:
        if v and v.strip():
            return v.strip()
    return ""


def _table_value(out: str) -> str:
    """wmic / powershell 表格输出：丢掉表头，取第一条非空数据行。"""
    lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
    if not lines:
        return ""
    if len(lines) >= 2 and re.fullmatch(r"[A-Za-z]+", lines[0]):
        return lines[1]
    return lines[0] if not re.fullmatch(r"[A-Za-z]+", lines[0]) else ""


def _collect_macos(run) -> dict[str, str]:
    raw: dict[str, str] = {}
    out = _safe(run, ["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"])
    m = re.search(r'"IOPlatformUUID"\s*=\s*"([^"]*)"', out)
    if m:
        raw["platform_uuid"] = m.group(1)
    m = re.search(r'"IOPlatformSerialNumber"\s*=\s*"([^"]*)"', out)
    if m:
        raw["serial"] = m.group(1)
    out = _safe(run, ["diskutil", "info", "/"])
    for pat in (r"Volume UUID:\s*(\S+)", r"Disk / Partition UUID:\s*(\S+)"):
        m = re.search(pat, out)
        if m:
            raw["disk_uuid"] = m.group(1)
            break
    return raw


def _ps(run, expr: str) -> str:
    return _safe(run, ["powershell", "-NoProfile", "-Command", expr])


def _collect_windows(run, use_winreg: bool) -> dict[str, str]:
    raw: dict[str, str] = {}
    guid = ""
    if use_winreg and winreg is not None:
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography",
                                0, winreg.KEY_READ | getattr(winreg, "KEY_WOW64_64KEY", 0)) as k:
                guid = str(winreg.QueryValueEx(k, "MachineGuid")[0])
        except Exception:
            guid = ""
    if not guid:
        out = _safe(run, ["reg", "query", r"HKLM\SOFTWARE\Microsoft\Cryptography",
                          "/v", "MachineGuid"])
        m = re.search(r"MachineGuid\s+REG_SZ\s+(\S+)", out)
        guid = m.group(1) if m else ""
    if guid:
        raw["machine_guid"] = guid

    specs = [
        ("board_serial", ["wmic", "baseboard", "get", "serialnumber"],
         "(Get-CimInstance Win32_BaseBoard).SerialNumber"),
        ("cpu_id", ["wmic", "cpu", "get", "processorid"],
         "(Get-CimInstance Win32_Processor | Select-Object -First 1).ProcessorId"),
        ("disk_serial", ["wmic", "diskdrive", "where", "index=0", "get", "serialnumber"],
         "(Get-CimInstance Win32_DiskDrive | Sort-Object Index | Select-Object -First 1).SerialNumber"),
    ]
    for key, wcmd, pscmd in specs:
        v = _table_value(_safe(run, wcmd))
        if not v:
            v = _table_value(_ps(run, pscmd))
        if v:
            raw[key] = v
    return raw


def _collect_linux(run) -> dict[str, str]:
    raw: dict[str, str] = {}
    mid = _first_nonempty(_safe(run, ["cat", "/etc/machine-id"]),
                          _safe(run, ["cat", "/var/lib/dbus/machine-id"]))
    if mid:
        raw["machine_id"] = mid
    dmi = _safe(run, ["cat", "/sys/class/dmi/id/product_uuid"])
    if dmi.strip():
        raw["dmi_uuid"] = dmi
    out = _safe(run, ["lsblk", "-dno", "SERIAL"])
    s = _first_nonempty(*out.splitlines())
    if s:
        raw["disk_serial"] = s
    return raw


def collect_raw(runner=None) -> dict[str, str]:
    """采集各来源原始值。runner(cmd_list)->str，失败应返回空串或抛异常（都会被忽略）。"""
    use_winreg = runner is None
    run = runner or _default_runner
    system = platform.system()
    try:
        if system == "Darwin":
            return _collect_macos(run)
        if system == "Windows":
            return _collect_windows(run, use_winreg)
        if system == "Linux":
            return _collect_linux(run)
    except Exception:
        return {}
    return {}


# ---------------------------------------------------------------- 计算

def _normalize(v: str) -> str:
    return re.sub(r"\s+", "", v or "").lower()


def _is_placeholder(n: str) -> bool:
    if n in _PLACEHOLDERS:
        return True
    if re.fullmatch(r"[0\-:.]*", n):          # 全 0
        return True
    if re.fullmatch(r"[f\-:.]+", n):          # 全 f
        return True
    return False


def compute_components(raw: dict[str, str], salt: bytes = PRODUCT_SALT) -> list[str]:
    comps = []
    for name in sorted(raw):
        n = _normalize(raw[name])
        if _is_placeholder(n):
            continue
        digest = hmac.new(salt, f"{name}:{n}".encode("utf-8"), hashlib.sha256).digest()
        comps.append(digest[:COMPONENT_BYTES].hex())
    if len(comps) < 2:
        raise InsufficientFingerprint(f"有效硬件来源不足 2 个（当前 {len(comps)} 个）")
    return comps


# ---------------------------------------------------------------- 格式化

def _crc10(values: list[int]) -> int:
    """对 5 位符号序列做 CRC-10（多项式 x^10+x^9+x^5+x^4+x+1），可检出任意单字符错误。"""
    poly, crc = 0x233, 0
    for v in values:
        for i in range(4, -1, -1):
            bit = (v >> i) & 1
            top = (crc >> 9) & 1
            crc = (crc << 1) & 0x3FF
            if top ^ bit:
                crc ^= poly
    return crc


def _check_chars(body: str) -> str:
    c = _crc10([_B32.index(ch) for ch in body])
    return _B32[c >> 5] + _B32[c & 31]


def format_machine_code(components: list[str]) -> str:
    if not 1 <= len(components) <= MAX_COMPONENTS:
        raise ValueError("分量个数不合法")
    data = bytes([len(components)])
    for c in components:
        b = bytes.fromhex(c)
        if len(b) != COMPONENT_BYTES:
            raise ValueError("分量长度不合法")
        data += b
    body = base64.b32encode(data).decode().rstrip("=")
    s = body + _check_chars(body)
    return "-".join(s[i:i + 5] for i in range(0, len(s), 5))


def parse_machine_code(code: str) -> list[str]:
    s = re.sub(r"[\s\-_]+", "", code or "").upper()
    # 易混字符：0->O，1->I；8、9 不在字符集内，明确拒绝
    s = s.replace("0", "O").replace("1", "I")
    bad = sorted({ch for ch in s if ch not in _B32})
    if bad:
        raise ValueError("机器码包含无效字符：" + "".join(bad))
    if len(s) < 3:
        raise ValueError("机器码校验失败，请检查是否复制完整")
    body, chk = s[:-2], s[-2:]
    if _check_chars(body) != chk:
        raise ValueError("机器码校验失败，请检查是否复制完整")
    pad = "=" * (-len(body) % 8)
    try:
        data = base64.b32decode(body + pad)
    except Exception:
        raise ValueError("机器码校验失败，请检查是否复制完整")
    if not data or len(data) != 1 + data[0] * COMPONENT_BYTES or data[0] > MAX_COMPONENTS:
        raise ValueError("机器码校验失败，请检查是否复制完整")
    return [data[1 + i * COMPONENT_BYTES: 1 + (i + 1) * COMPONENT_BYTES].hex()
            for i in range(data[0])]


def match(a: list[str], b: list[str], min_match: int = 2) -> bool:
    sa, sb = set(a), set(b)
    if not sa or not sb:
        return False
    need = min(min_match, len(sa), len(sb))
    if min(len(sa), len(sb)) < min_match:
        need = min(len(sa), len(sb))
        # 分量不足时要求较小一方全部命中
        return len(sa & sb) >= need and (sa <= sb or sb <= sa)
    return len(sa & sb) >= need


def get_components(salt: bytes = PRODUCT_SALT) -> list[str]:
    return compute_components(collect_raw(), salt)


def get_machine_code(salt: bytes = PRODUCT_SALT) -> str:
    return format_machine_code(get_components(salt))


def main() -> int:
    try:
        comps = get_components()
    except InsufficientFingerprint as e:
        print(f"无法生成机器码：{e}", file=sys.stderr)
        return 1
    print(f"机器码：{format_machine_code(comps)}")
    print(f"有效来源数量：{len(comps)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
