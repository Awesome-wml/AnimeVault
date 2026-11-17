#!/usr/bin/env python3
"""版本单一来源（仓库根 VERSION）与 Electron 壳 desktop/shell/package.json 的同步与一致性检查。

用法：
    python3 desktop/sync_version.py            # 把 VERSION 写进 desktop/shell/package.json（和 package-lock.json 的顶层版本）
    python3 desktop/sync_version.py --check    # 只检查，不一致 exit 1（electron-builder 的 pre 钩子用）

desktop/build_backend.py 构建前会先同步再检查；npm run dist:* / pack 前会跑 --check，两处不一致时构建失败。
VERSION 只写 x.y.z（semver）；测试构建的 +testbuild 由构建脚本加在产物里，不写进 VERSION。
"""
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERSION_FILE = ROOT / "VERSION"
SHELL_PKG = ROOT / "desktop" / "shell" / "package.json"
SHELL_LOCK = ROOT / "desktop" / "shell" / "package-lock.json"
SEMVER = re.compile(r"^\d+\.\d+\.\d+(-[0-9A-Za-z.-]+)?$")


def read_version(path: Path = VERSION_FILE) -> str:
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError as e:
        raise SystemExit(f"读不到 {path}：{e}")
    v = text.splitlines()[0].strip() if text else ""
    if not SEMVER.match(v):
        raise SystemExit(f"{path} 里的版本号不合法：{v!r}（要求 x.y.z，不带 +testbuild，见 docs/versioning.md）")
    return v


def shell_version(pkg: Path = SHELL_PKG) -> str:
    return json.loads(pkg.read_text(encoding="utf-8")).get("version", "")


def _rewrite_json(path: Path, mutate) -> bool:
    raw = path.read_text(encoding="utf-8")
    data = json.loads(raw)
    if not mutate(data):
        return False
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return True


def sync_shell_version(version: str, pkg: Path = SHELL_PKG, lock: Path = SHELL_LOCK) -> bool:
    """把版本写进壳的 package.json（以及 lock 的顶层字段）；返回是否有改动。"""
    def set_pkg(d):
        if d.get("version") == version:
            return False
        d["version"] = version
        return True

    def set_lock(d):
        changed = d.get("version") != version
        d["version"] = version
        root = d.get("packages", {}).get("")
        if isinstance(root, dict) and root.get("version") != version:
            root["version"] = version
            changed = True
        return changed

    changed = _rewrite_json(pkg, set_pkg)
    if lock.exists():
        changed = _rewrite_json(lock, set_lock) or changed
    return changed


def check_consistent(version_file: Path = VERSION_FILE, pkg: Path = SHELL_PKG) -> str:
    """不一致抛 SystemExit（构建失败）；一致返回版本号。"""
    v = read_version(version_file)
    sv = shell_version(pkg)
    if sv != v:
        raise SystemExit(f"版本不一致：VERSION={v}，desktop/shell/package.json={sv}。"
                         "运行 python3 desktop/sync_version.py 同步后再构建")
    return v


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只检查一致性，不写文件")
    args = ap.parse_args()
    if args.check:
        print(f"版本一致：{check_consistent()}")
        return 0
    v = read_version()
    changed = sync_shell_version(v)
    print(f"{'已同步' if changed else '无需改动'}：desktop/shell 版本 = {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
