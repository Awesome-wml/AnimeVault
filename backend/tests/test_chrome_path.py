"""Chrome 路径按平台探测，不再写死 macOS；DOUBAO_CHROME_PATH 优先。"""
from core.doubao_chrome import chrome_candidates, find_chrome


def test_windows_candidates():
    env = {"PROGRAMFILES": r"C:\Program Files", "LOCALAPPDATA": r"C:\Users\u\AppData\Local"}
    cands = chrome_candidates("win32", env, "C:/Users/u")
    assert any(c.endswith("chrome.exe") and "Program Files" in c for c in cands)
    found = find_chrome("win32", env, "C:/Users/u", exists=lambda p: "AppData" in p)
    assert "AppData" in found and found.endswith("chrome.exe")


def test_env_override_wins():
    assert find_chrome("win32", {"DOUBAO_CHROME_PATH": "/x/chrome"}, "/h", exists=lambda p: False) == "/x/chrome"


def test_mac_and_linux():
    assert find_chrome("darwin", {}, "/Users/u", exists=lambda p: p.startswith("/Users/u")).startswith("/Users/u/Applications")
    assert find_chrome("linux", {}, "/home/u", exists=lambda p: p == "/usr/bin/google-chrome-stable") == "/usr/bin/google-chrome-stable"
