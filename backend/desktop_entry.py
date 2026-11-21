"""桌面版后端启动入口：由 Electron 外壳拉起。

流程：
1. 未设置 MONGODB_URL 时，拉起随包 mongod（只绑 127.0.0.1；DONGAI_MONGOD_AUTH=1 时开认证，默认不开），等它就绪；
2. 选空闲端口、生成一次性令牌，只绑定 127.0.0.1，启动 uvicorn；
3. 启动完成后在 stdout 打印一行 {"event":"ready","port":端口,"token":"令牌"} 供外壳读取；
4. 退出（正常、异常、SIGTERM、SIGINT）时优雅停止 mongod。

孤儿保护：mongod 启动后把 pid 写入 <数据目录>/mongod.pid。后端被强杀（kill -9）时来不及停 mongod，
下次启动先检查 mongod.pid（和 mongo/mongod.lock）里的进程：还活着且确实是 mongod 就先结束它，再启动新的。
（mongod 本身没有"父进程消失后自行退出"的选项，所以靠 pid 文件机制。）

隐藏参数 --build-info：打印构建信息 JSON（是否测试构建、内置公钥 kid、授权服务地址、版本号/平台/渠道）后退出，不启动服务。
正式发布前用 desktop/check_release_build.py 校验它。

隐藏参数 --selfcheck：不启动服务，只检查 Playwright 驱动能否被找到并启动、随包 ffmpeg/ffprobe 能否执行，打印 JSON 后退出。
"""
import json
import os
import secrets
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import List, Optional

MONGOD_BIN_ENV = "DONGAI_MONGOD_BIN"
PID_FILE_NAME = "mongod.pid"


def pick_free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ---------------------------------------------------------------- mongod 路径与遗留进程


def app_dir() -> Path:
    """可执行包所在目录。Nuitka 编译后取可执行文件所在目录，源码运行时取本文件所在目录。"""
    if "__compiled__" in globals() or getattr(sys, "frozen", False):
        return Path(os.path.abspath(sys.argv[0])).resolve().parent
    return Path(__file__).resolve().parent


def resolve_mongod_bin() -> Path:
    """随包 mongod 路径：环境变量 DONGAI_MONGOD_BIN 优先，否则可执行包旁边的 bin/mongod(.exe)。"""
    custom = os.environ.get(MONGOD_BIN_ENV, "").strip()
    if custom:
        return Path(custom).expanduser()
    name = "mongod.exe" if sys.platform == "win32" else "mongod"
    return app_dir() / "bin" / name


def mongo_data_dir(data_dir: Path) -> Path:
    return data_dir / "mongo"


def pid_file_path(data_dir: Path) -> Path:
    return data_dir / PID_FILE_NAME


def _pid_alive(pid: int) -> bool:
    from desktop.mongod_manager import _pid_alive as alive
    return alive(pid)


def _process_command(pid: int) -> Optional[str]:
    """返回进程的命令行/映像名，查不到（进程不存在）返回 None。"""
    try:
        if sys.platform == "win32":
            out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                                 capture_output=True, text=True, timeout=10,
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
            return out.strip() if str(pid) in out else None
        out = subprocess.run(["ps", "-p", str(pid), "-o", "command="],
                             capture_output=True, text=True, timeout=10).stdout.strip()
        return out or None
    except (OSError, subprocess.SubprocessError):
        return None


def is_mongod_process(pid: int) -> bool:
    """pid 存在且命令行里含 mongod（防止 pid 被系统复用给别的程序后误杀）。"""
    if pid <= 0 or pid == os.getpid() or not _pid_alive(pid):
        return False
    cmd = _process_command(pid)
    return bool(cmd) and "mongod" in cmd.lower()


def _read_pid(path: Path) -> int:
    try:
        text = path.read_text().strip().splitlines()[0]
        return int(text)
    except (OSError, ValueError, IndexError):
        return 0


def terminate_pid(pid: int, timeout: float = 10.0) -> bool:
    """先温和结束，超时强杀；返回进程是否已消失。"""
    try:
        os.kill(pid, signal.SIGTERM)  # Windows 上等价于 TerminateProcess
    except (ProcessLookupError, PermissionError, OSError):
        return not _pid_alive(pid)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _pid_alive(pid):
            return True
        time.sleep(0.1)
    if sys.platform != "win32":
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass
        for _ in range(50):
            if not _pid_alive(pid):
                return True
            time.sleep(0.1)
    return not _pid_alive(pid)


def cleanup_stale_mongod(data_dir: Path, stop_timeout: float = 10.0) -> List[int]:
    """结束上次遗留的 mongod，返回被结束的 pid 列表。

    候选 pid 来自 <data>/mongod.pid 和 <data>/mongo/mongod.lock；只处理确认是 mongod 的进程。
    清理完删除 pid 文件。
    """
    pidf = pid_file_path(data_dir)
    candidates = []
    for f in (pidf, mongo_data_dir(data_dir) / "mongod.lock"):
        pid = _read_pid(f)
        if pid and pid not in candidates:
            candidates.append(pid)
    killed = []
    for pid in candidates:
        if is_mongod_process(pid):
            if terminate_pid(pid, stop_timeout):
                killed.append(pid)
            else:
                raise RuntimeError(f"上次遗留的 mongod（pid={pid}）无法结束，请手动关闭后重试")
    try:
        pidf.unlink()
    except OSError:
        pass
    return killed


def start_local_mongod(data_dir: Path):
    """清理遗留进程、拉起随包 mongod 并等就绪；返回已启动的 MongodManager（连接串在 .url）。"""
    from desktop.mongod_manager import MongodError, MongodManager

    binary = resolve_mongod_bin()
    if not binary.exists():
        raise MongodError(f"找不到 mongod：{binary}（可用环境变量 {MONGOD_BIN_ENV} 指定）")
    data_dir.mkdir(parents=True, exist_ok=True)
    stale = cleanup_stale_mongod(data_dir)
    if stale:
        print(f"已清理上次遗留的 mongod 进程：{stale}", file=sys.stderr, flush=True)
    # 数据库认证开关（默认关）：DONGAI_MONGOD_AUTH=1 时 mongod 带 --auth 启动，首次生成随机账号密码存在数据目录里。
    # 默认关是因为这条启动路径还没有在真机上验证过；验证通过后把默认值改成开。
    auth = os.environ.get("DONGAI_MONGOD_AUTH", "").strip().lower() in ("1", "true", "yes", "on")
    mgr = MongodManager(binary, mongo_data_dir(data_dir), log_path=data_dir / "logs" / "mongod.log",
                        auth=auth, credentials_path=data_dir / "mongod.auth")
    mgr.start()
    pid_file_path(data_dir).write_text(f"{mgr.pid}\n", encoding="utf-8")
    return mgr


def stop_local_mongod(mgr, data_dir: Path) -> None:
    try:
        mgr.stop()
    finally:
        try:
            pid_file_path(data_dir).unlink()
        except OSError:
            pass


# ---------------------------------------------------------------- 自检


def selfcheck() -> int:
    """隐藏入口：检查 Playwright 驱动与 ffmpeg/ffprobe。不打开浏览器页面。"""
    result = {"python": sys.version.split()[0], "compiled": "__compiled__" in globals(), "ok": False}
    ffmpeg_ok = False
    try:
        from core import ffmpeg_locator
        result["ffmpeg"] = ffmpeg_locator.check()
        ffmpeg_ok = bool(result["ffmpeg"]["ok"])
    except Exception as e:  # noqa: BLE001
        result["ffmpeg_error"] = repr(e)
    try:
        import playwright
        from playwright._impl._driver import compute_driver_executable
        driver = Path(compute_driver_executable())
        root = driver.parent
        node = root / ("node.exe" if sys.platform == "win32" else "node")
        pkg = root / "package"
        result.update({
            "playwright_file": str(Path(playwright.__file__).resolve()),
            "driver_script": str(driver), "driver_script_exists": driver.exists(),
            "node": str(node), "node_exists": node.exists(), "node_executable": os.access(node, os.X_OK),
            "package_dir_exists": pkg.is_dir(),
            "package_json_exists": (pkg / "package.json").exists(),
            "cli_js_exists": (pkg / "cli.js").exists(),
        })
        if node.exists():
            r = subprocess.run([str(node), "--version"], capture_output=True, text=True, timeout=20)
            result["node_version"] = r.stdout.strip()
        try:
            result["driver_version"] = json.loads((pkg / "package.json").read_text())["version"]
        except Exception as e:  # noqa: BLE001
            result["driver_version_error"] = repr(e)

        def start_stop(key):
            from playwright.sync_api import sync_playwright
            try:
                pw = sync_playwright().start()
                pw.stop()
                result[key] = True
            except Exception as e:  # noqa: BLE001
                result[key] = False
                result[key + "_error"] = repr(e)

        start_stop("sync_playwright_start_main")
        t = threading.Thread(target=start_stop, args=("sync_playwright_start_thread",))
        t.start()
        t.join(60)
        result["ok"] = bool(result.get("sync_playwright_start_main") and result.get("sync_playwright_start_thread")
                            and result["node_executable"] and result["package_dir_exists"]
                            and result["driver_script_exists"] and ffmpeg_ok)
    except Exception as e:  # noqa: BLE001
        result["error"] = repr(e)
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return 0 if result["ok"] else 1


# ---------------------------------------------------------------- 主流程


def _install_exit_signals() -> None:
    """uvicorn 启动前（等 mongod 的这段时间）收到信号也要走 finally 清理；uvicorn 启动后会接管同样的信号。"""
    def handler(signum, frame):
        raise SystemExit(128 + signum)

    for name in ("SIGTERM", "SIGINT", "SIGBREAK"):
        sig = getattr(signal, name, None)
        if sig is not None:
            try:
                signal.signal(sig, handler)
            except (ValueError, OSError):
                pass


def _log_ffmpeg_status() -> None:
    """启动自检：ffmpeg/ffprobe 缺失只告警（不阻止启动，只有用到视频/音频处理的功能会失败并提示）。"""
    try:
        from core import ffmpeg_locator
        r = ffmpeg_locator.check()
        if not r["ok"]:
            print(f"警告：视频处理组件不可用：{json.dumps(r, ensure_ascii=False)}", file=sys.stderr, flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"警告：ffmpeg 自检失败：{e!r}", file=sys.stderr, flush=True)


def build_info() -> dict:
    from core import license_config, license_keys, version
    return {"test_build": license_keys.TEST_BUILD, "marker": license_keys.TEST_BUILD_MARKER,
            "kids": sorted(license_keys.PUBLIC_KEYS), "license_server": license_config.get_server_url(),
            "app_version": version.get_version(), "version": version.base_version(),
            "platform": version.get_platform(), "channel": version.get_channel()}


def main() -> None:
    os.environ.setdefault("DONGAI_APP_DIR", str(app_dir()))
    if "--build-info" in sys.argv[1:]:
        print(json.dumps(build_info(), ensure_ascii=False), flush=True)
        sys.exit(0)
    if "--selfcheck" in sys.argv[1:]:
        sys.exit(selfcheck())

    # 强制桌面模式：不能用 setdefault，否则 DONGAI_DESKTOP=0 就能关掉授权拦截（见 paths.force_desktop）
    os.environ["DONGAI_DESKTOP"] = "1"
    import uvicorn
    from config import paths
    paths.force_desktop()

    _install_exit_signals()
    _log_ffmpeg_status()
    _info = build_info()
    if _info["test_build"]:
        print(f"警告：【测试构建 {_info['marker']}】内置的是测试公钥 {_info['kids']}，授权服务地址 {_info['license_server']}，"
              "不得对外发布", file=sys.stderr, flush=True)
    mongod = None
    data_dir = paths.data_dir()
    try:
        if not os.environ.get("MONGODB_URL"):
            mongod = start_local_mongod(data_dir)
            os.environ["MONGODB_URL"] = mongod.url

        port = pick_free_port()
        token = secrets.token_urlsafe(32)
        os.environ["DONGAI_LOCAL_TOKEN"] = token

        import main as app_module  # 在令牌和 MONGODB_URL 设置之后再导入应用

        config = uvicorn.Config(app_module.app, host="127.0.0.1", port=port, loop="asyncio",
                                log_level="info", access_log=False)
        server = uvicorn.Server(config)

        def announce():
            # server.started 在 lifespan 启动完成（含 Mongo 连接）后置位
            while not server.started and thread.is_alive():
                time.sleep(0.1)
            if server.started:
                ready = {"event": "ready", "port": port, "token": token}
                if _info["test_build"]:
                    ready["test_build"] = True
                print(json.dumps(ready), flush=True)

        thread = threading.current_thread()
        threading.Thread(target=announce, daemon=True).start()
        server.run()
        if not server.started:
            sys.exit(1)
    finally:
        if mongod is not None:
            stop_local_mongod(mongod, data_dir)


if __name__ == "__main__":
    main()
