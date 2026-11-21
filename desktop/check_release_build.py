#!/usr/bin/env python3
"""发布前检查：确认产物是正式构建，不含「构建期测试公钥」（desktop/build_backend.py --test-public-key）。

用法：
    python desktop/check_release_build.py [--dist desktop/dist/dongai-backend] [--expect-test]
    --expect-test  反向：断言产物是测试构建（给 e2e/冒烟脚本确认自己测的是测试包）

检查项（任何一项不满足 exit 1）：
  1 源码树里没有 backend/core/_test_build.py（构建脚本编译后会删，残留说明构建被中断）；
  2 dist/BUILD_INFO.json 里 test_build 为 false；
  3 实际运行 `<exe> --build-info`（以编译进去的代码为准，不信 json 文件）：test_build 为 false、
    授权服务地址不是本机地址、版本号不带 +testbuild；
  4 产物文件里扫不到测试标记串（兜底：即使 --build-info 被改过也能发现）；
    正式包的授权服务地址不能是 example.com 占位、内置公钥不能含开发占位 kid（--allow-placeholder 只提醒）。
  5 版本一致性：仓库根 VERSION == desktop/shell/package.json == BUILD_INFO.json 的 version == --build-info 的 version
    （--build-info 的 app_version 去掉 +testbuild 后也要相等），平台是 mac-arm64|mac-x64|win-x64 之一。
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import sync_version  # noqa: E402

RELEASE_PLATFORMS = ("mac-arm64", "mac-x64", "win-x64")
MARKER = b"DONGAI-TEST-BUILD-"
DEV_PLACEHOLDER_KID = "1a8c8d43"  # core/license_keys.py 的开发占位公钥
IS_WIN = sys.platform == "win32"


def scan_marker(dist: Path) -> list:
    hits = []
    for p in dist.rglob("*"):
        if not p.is_file() or p.is_symlink():
            continue
        try:
            size = p.stat().st_size
            if size > 400 * 1024 * 1024:   # mongod/ffmpeg 等大二进制不是我们编的，跳过
                continue
            with open(p, "rb") as f:
                prev = b""
                while True:
                    chunk = f.read(8 * 1024 * 1024)
                    if not chunk:
                        break
                    if MARKER in prev[-len(MARKER):] + chunk:
                        hits.append(str(p.relative_to(dist)))
                        break
                    prev = chunk
        except OSError:
            continue
    return hits


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dist", default=str(ROOT / "desktop" / "dist" / "dongai-backend"))
    ap.add_argument("--expect-test", action="store_true")
    ap.add_argument("--allow-placeholder", action="store_true",
                    help="内部预览包：授权地址/公钥仍是占位时只提醒不失败（不得对外发布）")
    args = ap.parse_args()
    dist = Path(args.dist)
    exe = dist / ("dongai-backend.exe" if IS_WIN else "dongai-backend")
    want_test = args.expect_test
    allow_placeholder = args.allow_placeholder
    problems = []

    leftover = ROOT / "backend" / "core" / "_test_build.py"
    if leftover.exists():
        problems.append(f"源码树里残留 {leftover}（构建被中断？删掉后重新构建）")
    print(f"[1] 源码树无 _test_build.py：{'否' if leftover.exists() else '是'}")

    version_file = sync_version.read_version()
    shell_ver = sync_version.shell_version()
    print(f"[5] VERSION={version_file}  desktop/shell/package.json={shell_ver}")
    if shell_ver != version_file:
        problems.append(f"版本不一致：VERSION={version_file}，desktop/shell/package.json={shell_ver}")

    info_file = dist / "BUILD_INFO.json"
    if info_file.exists():
        build_json = json.loads(info_file.read_text())
        flag = build_json.get("test_build")
        print(f"[2] BUILD_INFO.json test_build={flag} version={build_json.get('version')} platform={build_json.get('platform')}")
        if build_json.get("version") != version_file:
            problems.append(f"BUILD_INFO.json version={build_json.get('version')}，与 VERSION={version_file} 不一致")
        if flag != want_test:
            problems.append(f"BUILD_INFO.json test_build={flag}，期望 {want_test}")
    else:
        print("[2] 没有 BUILD_INFO.json")
        problems.append("缺少 BUILD_INFO.json（不是 build_backend.py 产出的包？）")

    if not exe.exists():
        problems.append(f"找不到可执行文件 {exe}")
    else:
        r = subprocess.run([str(exe), "--build-info"], capture_output=True, text=True, timeout=120,
                           env={**os.environ, "DONGAI_DATA_DIR": str(ROOT / "desktop" / "build" / ".check-data")})
        try:
            info = json.loads(r.stdout.strip().splitlines()[-1])
        except Exception:  # noqa: BLE001
            info = None
            problems.append(f"--build-info 没有输出 JSON：rc={r.returncode} {r.stdout[-200:]} {r.stderr[-200:]}")
        if info is not None:
            print(f"[3] --build-info：{json.dumps(info, ensure_ascii=False)}")
            if info.get("version") != version_file:
                problems.append(f"--build-info version={info.get('version')}，与 VERSION={version_file} 不一致")
            if info.get("app_version", "").split("+")[0] != version_file:
                problems.append(f"--build-info app_version={info.get('app_version')}，与 VERSION={version_file} 不一致")
            if info.get("platform") not in RELEASE_PLATFORMS:
                problems.append(f"--build-info platform={info.get('platform')}，应为 {'|'.join(RELEASE_PLATFORMS)}")
            if bool(info.get("test_build")) != want_test:
                problems.append(f"--build-info test_build={info.get('test_build')}，期望 {want_test}")
            if not want_test:
                if "testbuild" in info.get("app_version", ""):
                    problems.append("版本号带 +testbuild")
                host = info.get("license_server", "")
                if any(x in host for x in ("127.0.0.1", "localhost")):
                    problems.append(f"授权服务地址是本机地址：{host}")
                placeholder = []
                if "example.com" in host:
                    placeholder.append(f"授权服务地址仍是占位 {host}（core/license_config.py）")
                if DEV_PLACEHOLDER_KID in (info.get("kids") or []):
                    placeholder.append(f"内置公钥仍含开发占位 kid {DEV_PLACEHOLDER_KID}（core/license_keys.py）")
                for msg in placeholder:
                    if allow_placeholder:
                        print(f"    提醒：{msg}；--allow-placeholder 已放行，此包不得对外发布")
                    else:
                        problems.append(f"{msg}，正式包必须替换（内部预览包可加 --allow-placeholder）")
        hits = scan_marker(dist)
        print(f"[4] 文件内扫描测试标记串：{'命中 ' + str(hits) if hits else '未命中'}")
        if bool(hits) != want_test:
            problems.append(f"测试标记串扫描结果 {hits}，期望{'有' if want_test else '没有'}")

    if problems:
        print("\n检查未通过：")
        for p in problems:
            print(" -", p)
        return 1
    print(f"\n检查通过：产物是{'测试' if want_test else '正式'}构建")
    return 0


if __name__ == "__main__":
    sys.exit(main())
