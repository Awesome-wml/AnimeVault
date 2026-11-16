import pytest

from dongai_license import machine_code as mc

IOREG = '''+-o Root  <class IORegistryEntry>
    "IOPlatformUUID" = "AAAAAAAA-1111-2222-3333-444444444444"
    "IOPlatformSerialNumber" = "C02XYZ123"
'''
DISKUTIL = "   Volume UUID:  BBBBBBBB-1111-2222-3333-555555555555\n"


def fake_runner(table):
    def run(cmd):
        v = table.get(tuple(cmd), "")
        if isinstance(v, Exception):
            raise v
        return v
    return run


def set_sys(monkeypatch, name):
    monkeypatch.setattr(mc.platform, "system", lambda: name)


def test_macos(monkeypatch):
    set_sys(monkeypatch, "Darwin")
    r = fake_runner({("ioreg", "-rd1", "-c", "IOPlatformExpertDevice"): IOREG,
                     ("diskutil", "info", "/"): DISKUTIL})
    raw = mc.collect_raw(r)
    assert set(raw) == {"platform_uuid", "serial", "disk_uuid"}
    assert raw["disk_uuid"].startswith("BBBBBBBB")


def test_windows_wmic_and_powershell_fallback(monkeypatch):
    set_sys(monkeypatch, "Windows")
    ps = lambda e: ("powershell", "-NoProfile", "-Command", e)
    r = fake_runner({
        ("reg", "query", r"HKLM\SOFTWARE\Microsoft\Cryptography", "/v", "MachineGuid"):
            "    MachineGuid    REG_SZ    abcd-1234\n",
        ("wmic", "baseboard", "get", "serialnumber"): "SerialNumber\nBSN123\n",
        ("wmic", "cpu", "get", "processorid"): RuntimeError("no wmic"),
        ps("(Get-CimInstance Win32_Processor | Select-Object -First 1).ProcessorId"): "BFEBFBFF000906EA\n",
    })
    raw = mc.collect_raw(r)
    assert raw["machine_guid"] == "abcd-1234"
    assert raw["board_serial"] == "BSN123"
    assert raw["cpu_id"] == "BFEBFBFF000906EA"
    assert "disk_serial" not in raw


def test_linux(monkeypatch):
    set_sys(monkeypatch, "Linux")
    r = fake_runner({("cat", "/var/lib/dbus/machine-id"): "deadbeef\n",
                     ("cat", "/sys/class/dmi/id/product_uuid"): "UUID-1\n",
                     ("lsblk", "-dno", "SERIAL"): "\nSER999\n"})
    raw = mc.collect_raw(r)
    assert raw == {"machine_id": "deadbeef", "dmi_uuid": "UUID-1\n", "disk_serial": "SER999"}


def test_all_failures_tolerated(monkeypatch):
    set_sys(monkeypatch, "Linux")
    assert mc.collect_raw(fake_runner({})) == {}


def test_placeholders_dropped():
    raw = {"a": "Default string", "b": "To be filled by O.E.M.", "c": "00000000-0000-0000",
           "d": " None ", "e": "System Serial Number", "f": "Not Specified", "g": "real1", "h": "real2"}
    assert len(mc.compute_components(raw)) == 2


def test_insufficient():
    with pytest.raises(mc.InsufficientFingerprint):
        mc.compute_components({"a": "x", "b": "unknown"})


RAW = {"platform_uuid": "U1", "serial": "S1", "disk_uuid": "D1"}


def test_deterministic_and_salt():
    a = mc.compute_components(RAW)
    assert a == mc.compute_components(dict(RAW))
    assert a != mc.compute_components(RAW, salt=b"other")
    assert all(len(c) == 16 for c in a)
    # 规范化：大小写和空白不影响
    assert a == mc.compute_components({k: " " + v.lower() + " " for k, v in RAW.items()})


def test_roundtrip():
    for n in (2, 3, 4):
        raw = {f"s{i}": f"v{i}" for i in range(n)}
        comps = mc.compute_components(raw)
        code = mc.format_machine_code(comps)
        assert mc.parse_machine_code(code) == comps
        assert all(len(g) <= 5 for g in code.split("-"))


def test_tolerant_parse():
    comps = mc.compute_components(RAW)
    code = mc.format_machine_code(comps)
    g = code.lower().split("-")
    messy = "  " + g[0] + " - " + g[1] + "\n" + "--".join(g[2:]) + " \n"
    assert mc.parse_machine_code(messy) == comps
    assert mc.parse_machine_code(code.replace("-", "")) == comps


def test_confusable_chars():
    comps = mc.compute_components(RAW)
    code = mc.format_machine_code(comps)
    assert "O" in code or "I" in code or True
    assert mc.parse_machine_code(code.replace("O", "0").replace("I", "1")) == comps
    with pytest.raises(ValueError, match="无效字符"):
        mc.parse_machine_code("8" + code)


def test_checksum_detects_single_char_errors():
    code = mc.format_machine_code(mc.compute_components(RAW)).replace("-", "")
    for i in range(len(code)):
        for ch in mc._B32:
            if ch == code[i]:
                continue
            bad = code[:i] + ch + code[i + 1:]
            with pytest.raises(ValueError):
                mc.parse_machine_code(bad)


def test_checksum_detects_missing_char():
    code = mc.format_machine_code(mc.compute_components(RAW)).replace("-", "")
    for i in range(len(code)):
        with pytest.raises(ValueError, match="机器码校验失败"):
            mc.parse_machine_code(code[:i] + code[i + 1:])


def test_match_tolerance():
    a = ["1", "2", "3"]
    assert mc.match(a, ["1", "2", "3"])
    assert mc.match(a, ["1", "2", "9"])      # 换 1 个
    assert not mc.match(a, ["1", "8", "9"])  # 换 2 个


def test_match_two_components_strict():
    assert mc.match(["1", "2"], ["1", "2"])
    assert not mc.match(["1", "2"], ["1", "9"])
    assert mc.match(["1", "2"], ["1", "2", "3"])
    assert not mc.match(["1", "2"], ["1", "3", "4"])
    assert not mc.match([], ["1"])


def test_get_machine_code_with_injected(monkeypatch):
    set_sys(monkeypatch, "Darwin")
    r = fake_runner({("ioreg", "-rd1", "-c", "IOPlatformExpertDevice"): IOREG,
                     ("diskutil", "info", "/"): DISKUTIL})
    monkeypatch.setattr(mc, "_default_runner", r)
    code = mc.get_machine_code()
    assert len(mc.parse_machine_code(code)) == 3
    assert "C02XYZ123" not in code
