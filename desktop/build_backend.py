#!/usr/bin/env python3
"""用 Nuitka 把后端打成 standalone 目录（L-05）。

用法（在装有 Nuitka 的 Python 里运行，默认 ~/.local/dongai-venv）：
    DONGAI_MONGOD_BIN=/path/to/mongod ~/.local/dongai-venv/bin/python desktop/build_backend.py [--jobs N] [--lto] [--clean]

产物：desktop/dist/dongai-backend/（可执行文件 dongai-backend[.exe]、bin/mongod[.exe]、playwright/driver 等），
中间文件在 desktop/build/。两个目录都已被 .gitignore 忽略，不提交。
Windows 打包要在 Windows 上做，参数差异见 desktop/README.md（本脚本里 Windows 分支未实测）。
"""
import argparse
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
LICENSE_LIB = ROOT / "license"
DESKTOP = ROOT / "desktop"
BUILD = DESKTOP / "build"
DIST = DESKTOP / "dist"
APP_NAME = "dongai-backend"
IS_WIN = sys.platform == "win32"

# backend 下的顶层包（都以源码形式编译进包）
BACKEND_PACKAGES = ["api", "config", "core", "db", "desktop", "models", "utils"]
# 动态加载 / 隐式导入的第三方包（整包带上，宁可大一点也不要运行时缺模块）
THIRD_PARTY_PACKAGES = [
    "uvicorn", "uvloop", "httptools", "websockets", "watchfiles", "yaml", "dotenv",
    "motor", "pymongo", "bson", "gridfs", "dns",
    "passlib", "bcrypt", "jose", "ecdsa", "cryptography", "keyring",
    "pydantic", "pydantic_settings", "multipart", "redis", "srt",
    "playwright",
]
EXTRA_MODULES = ["main", "srt"]


def run(cmd, **kw):
    print("+", " ".join(map(str, cmd)), flush=True)
    subprocess.run(cmd, check=True, **kw)


def nuitka_cmd(jobs: int, lto: bool):
    cmd = [
        sys.executable, "-m", "nuitka",
        "--standalone",
        f"--output-dir={BUILD}",
        f"--output-filename={APP_NAME}",
        "--assume-yes-for-downloads",
        f"--jobs={jobs}",
        f"--lto={'yes' if lto else 'no'}",
        "--remove-output",
        "--nofollow-import-to=pytest,_pytest,tests",
        # 提示词等数据文件（core/prompt_registry.py 用 __file__ 同级的 prompts/ 读取）
        f"--include-data-dir={BACKEND / 'core' / 'prompts'}=core/prompts",
    ]
    for p in BACKEND_PACKAGES + THIRD_PARTY_PACKAGES + ["dongai_license"]:
        cmd.append(f"--include-package={p}")
    for m in EXTRA_MODULES:
        cmd.append(f"--include-module={m}")
    # playwright/driver/package（JS）由 Nuitka 自带的 playwright 配置带上；node 二进制会被它当成可执行文件
    # 与数据文件冲突（FATAL: data file ... conflicts with exe），所以排除，构建后由 ensure_playwright_driver 补回
    cmd.append("--noinclude-data-files=playwright/driver/node")
    if sys.platform == "darwin":
        pass  # 命令行可执行文件，不生成 .app
    if IS_WIN:
        # 未实测：见 README。发布版用 disable，调试时用 force 看到控制台
        cmd += ["--windows-console-mode=attach"]
    cmd.append(str(BACKEND / "desktop_entry.py"))
    return cmd


def find_driver_src() -> Path:
    import playwright
    return Path(playwright.__file__).resolve().parent / "driver"


def ensure_playwright_driver(dist_app: Path) -> None:
    """playwright/driver 必须完整：node 可执行 + package/ + playwright.sh|cmd。缺了或没有执行权限就从 site-packages 补。"""
    src = find_driver_src()
    dst = dist_app / "playwright" / "driver"
    # Nuitka 不会带上 playwright.sh / playwright.cmd（selfcheck 实测：启动时 FileNotFoundError），
    # 所以整目录以原始文件覆盖一遍：保证 node（保留官方原件）、package/、启动脚本齐全
    shutil.copytree(src, dst, symlinks=True, dirs_exist_ok=True)
    if not IS_WIN:
        for f in ("node", "playwright.sh"):
            p = dst / f
            if p.exists():
                p.chmod(p.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    node = dst / ("node.exe" if IS_WIN else "node")
    assert node.exists() and os.access(node, os.X_OK), f"playwright node 不可执行：{node}"
    assert (dst / "package" / "cli.js").exists(), "playwright/driver/package 缺失"
    print(f"playwright 驱动就绪：{dst}", flush=True)


def bundle_fake_fixtures(dist_app: Path) -> None:
    """替身供应商（DONGAI_FAKE_PROVIDERS=1，开发/冒烟用）从 <包根>/tests/fixtures 读占位图、音频、视频。"""
    src = BACKEND / "tests" / "fixtures"
    dst = dist_app / "tests" / "fixtures"
    shutil.copytree(src, dst, dirs_exist_ok=True)
    print(f"替身供应商夹具已复制到 {dst}", flush=True)


def bundle_mongod(dist_app: Path, mongod_src: Path) -> None:
    if not mongod_src.exists():
        raise SystemExit(f"找不到 mongod：{mongod_src}（用环境变量 DONGAI_MONGOD_BIN 指定官方社区版 mongod）")
    bin_dir = dist_app / "bin"
    bin_dir.mkdir(exist_ok=True)
    dst = bin_dir / ("mongod.exe" if IS_WIN else "mongod")
    shutil.copy2(mongod_src, dst)
    if not IS_WIN:
        dst.chmod(0o755)
    # SSPL 随包分发要求附带许可证文本与第三方声明（官方包里与 bin/ 同级）
    lic_dir = bin_dir.parent / "licenses" / "mongodb"
    lic_dir.mkdir(parents=True, exist_ok=True)
    for name in ("LICENSE-Community.txt", "THIRD-PARTY-NOTICES", "MPL-2", "README"):
        f = mongod_src.resolve().parent.parent / name
        if f.exists():
            shutil.copy2(f, lic_dir / name)
    print(f"mongod 已放入 {dst}（{dst.stat().st_size / 1e6:.0f} MB）", flush=True)


def bundle_ffmpeg(dist_app: Path, ffmpeg_dir: Path) -> None:
    """把 ffmpeg 和 ffprobe 复制到 <包根>/bin/（解析顺序见 backend/core/ffmpeg_locator.py）。
    许可证文本（LGPL 构建的 LICENSE/源码获取说明）请一并放进 --ffmpeg-dir/licenses/，会复制到 licenses/ffmpeg/。"""
    bin_dir = dist_app / "bin"
    bin_dir.mkdir(exist_ok=True)
    for tool in ("ffmpeg", "ffprobe"):
        name = tool + (".exe" if IS_WIN else "")
        src = ffmpeg_dir / name
        if not src.is_file():
            raise SystemExit(f"--ffmpeg-dir 里找不到 {name}：{src}")
        dst = bin_dir / name
        shutil.copy2(src, dst)
        if not IS_WIN:
            dst.chmod(0o755)
        print(f"{tool} 已放入 {dst}（{dst.stat().st_size / 1e6:.0f} MB）", flush=True)
    lic = ffmpeg_dir / "licenses"
    if lic.is_dir():
        shutil.copytree(lic, dist_app / "licenses" / "ffmpeg", dirs_exist_ok=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", type=int, default=os.cpu_count() or 4)
    ap.add_argument("--lto", action="store_true", help="开启 LTO（更小更快，但编译慢很多）")
    ap.add_argument("--clean", action="store_true", help="先删除 build/ 和 dist/")
    ap.add_argument("--no-fixtures", action="store_true", help="不带替身供应商夹具（正式发布包可用）")
    ap.add_argument("--ffmpeg-dir", default="", help="含 ffmpeg 和 ffprobe 的目录（可选），复制到包内 bin/；不带则运行时依赖系统 PATH，见 docs/ffmpeg-bundling.md")
    ap.add_argument("--skip-nuitka", action="store_true", help="只重做后处理（驱动校验、拷贝 mongod）")
    args = ap.parse_args()

    mongod_env = os.environ.get("DONGAI_MONGOD_BIN", "").strip()
    if not mongod_env:
        raise SystemExit("请设置 DONGAI_MONGOD_BIN 指向官方社区版 mongod 二进制")
    if args.clean:
        shutil.rmtree(BUILD, ignore_errors=True)
        shutil.rmtree(DIST, ignore_errors=True)
    BUILD.mkdir(parents=True, exist_ok=True)
    DIST.mkdir(parents=True, exist_ok=True)

    if not args.skip_nuitka:
        env = dict(os.environ)
        # 让 Nuitka 找得到 backend 的顶层模块和共享库 dongai_license
        env["PYTHONPATH"] = os.pathsep.join([str(BACKEND), str(LICENSE_LIB), env.get("PYTHONPATH", "")]).rstrip(os.pathsep)
        run(nuitka_cmd(args.jobs, args.lto), cwd=BACKEND, env=env)

    built = BUILD / "desktop_entry.dist"
    if not built.exists():
        raise SystemExit(f"没找到 Nuitka 产物 {built}")
    dist_app = DIST / APP_NAME
    if dist_app.exists():
        shutil.rmtree(dist_app)
    shutil.copytree(built, dist_app, symlinks=True)
    ensure_playwright_driver(dist_app)
    if not args.no_fixtures:
        bundle_fake_fixtures(dist_app)
    bundle_mongod(dist_app, Path(mongod_env).expanduser())
    if args.ffmpeg_dir:
        bundle_ffmpeg(dist_app, Path(args.ffmpeg_dir).expanduser())
    else:
        print("提示：未指定 --ffmpeg-dir，包内没有 ffmpeg/ffprobe，运行时将依赖系统 PATH", flush=True)
    exe = dist_app / (APP_NAME + (".exe" if IS_WIN else ""))
    print(f"完成：{exe}", flush=True)


if __name__ == "__main__":
    main()
