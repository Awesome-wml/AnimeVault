"""
豆包账号的系统 Chrome：启动（带调试端口）、探测、资料目录锁、登录检查。

- launch_chrome：添加账号 / 未登录弹窗 / 「打开」三处共用。统一带
  --remote-debugging-port=<账号端口> --remote-debugging-address=127.0.0.1，
  之后检查登录可以直接连上这个窗口读 cookie，不用再抢同一个资料目录。
- 端口存在账号文档的 debug_port 字段，首次用到时分配（account_N 优先用 BASE+N），多个账号不冲突。
- check_account_login：检查登录的完整流程，带总超时，Playwright 跑在可被整组杀掉的子进程里。
"""
import asyncio
import json
import logging
import os
import re
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Iterable, List, Optional

logger = logging.getLogger(__name__)

_MAC_CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


def chrome_candidates(platform: Optional[str] = None, env: Optional[dict] = None, home: Optional[str] = None) -> List[str]:
    """各平台 Google Chrome 可执行文件的常见位置（与 desktop/shell/src/chrome-check.js 的检测口径一致）。"""
    platform = platform or sys.platform
    env = os.environ if env is None else env
    home = home or str(Path.home())
    if platform == "darwin":
        return [_MAC_CHROME, os.path.join(home, "Applications", "Google Chrome.app", "Contents", "MacOS", "Google Chrome")]
    if platform.startswith("win"):
        roots = [env.get("PROGRAMFILES"), env.get("PROGRAMFILES(X86)"), env.get("LOCALAPPDATA")]
        return [os.path.join(r, "Google", "Chrome", "Application", "chrome.exe") for r in roots if r]
    return ["/usr/bin/google-chrome", "/usr/bin/google-chrome-stable", "/opt/google/chrome/chrome"]


def find_chrome(platform: Optional[str] = None, env: Optional[dict] = None, home: Optional[str] = None,
                exists=os.path.exists) -> str:
    """Chrome 路径：环境变量 DOUBAO_CHROME_PATH 优先，其次各平台常见位置；都没有时返回第一个候选（启动时报“未安装”）。

    原来写死 macOS 路径，Windows 用户必须自己设环境变量、界面上没有任何提示。
    """
    env = os.environ if env is None else env
    custom = (env.get("DOUBAO_CHROME_PATH") or "").strip()
    if custom:
        return custom
    cands = chrome_candidates(platform, env, home)
    for c in cands:
        if exists(c):
            return c
    return cands[0] if cands else _MAC_CHROME


CHROME_PATH = find_chrome()


class ChromeNotFoundError(Exception):
    """找不到 Google Chrome（文案可直接给用户看）"""
DOUBAO_CHAT_URL = "https://www.doubao.com/chat/"
DEBUG_PORT_BASE = 19300
DEBUG_PORT_SPAN = 600          # 端口范围 [19300, 19900)
CHECK_TIMEOUT_SECONDS = 45     # 一次登录检查的总超时
BACKEND_DIR = Path(__file__).resolve().parent.parent


class LoginCheckError(Exception):
    """登录检查失败（文案可直接给用户看）"""
    status_code = 500


class ProfileInUse(LoginCheckError):
    status_code = 409


class LoginCheckTimeout(LoginCheckError):
    status_code = 504


class LoginCheckBusy(LoginCheckError):
    status_code = 409


# ------------------------------------------------------------------ 端口
def preferred_port(account_id: str) -> Optional[int]:
    m = re.fullmatch(r"account_(\d+)", account_id or "")
    if m and 0 < int(m.group(1)) < DEBUG_PORT_SPAN:
        return DEBUG_PORT_BASE + int(m.group(1))
    return None


def allocate_port(account_id: str, used: Iterable[int]) -> int:
    used = set(p for p in used if p)
    pref = preferred_port(account_id)
    if pref and pref not in used:
        return pref
    for port in range(DEBUG_PORT_BASE + DEBUG_PORT_SPAN - 1, DEBUG_PORT_BASE, -1):
        if port not in used:
            return port
    raise RuntimeError("没有可用的调试端口")


def ensure_debug_port(pool, account: dict) -> int:
    """返回账号的调试端口；没有就分配一个并写回账号文档。"""
    port = account.get("debug_port")
    if port:
        return int(port)
    used = [a.get("debug_port") for a in pool.accounts if a.get("id") != account.get("id")]
    port = allocate_port(account["id"], used)
    pool.update_account(account["id"], {"debug_port": port})
    account["debug_port"] = port
    return port


# ------------------------------------------------------------------ 启动 / 探测
def chrome_args(profile_path: str, port: int, url: str = DOUBAO_CHAT_URL, extra_args: Optional[List[str]] = None) -> list:
    return [
        CHROME_PATH,
        f"--user-data-dir={profile_path}",
        f"--remote-debugging-port={port}",
        "--remote-debugging-address=127.0.0.1",
        "--password-store=basic",
        "--use-mock-keychain",
        "--no-first-run",
        "--no-default-browser-check",
        *(extra_args or []),
        url,
    ]


def launch_chrome(profile_path: str, port: int, url: str = DOUBAO_CHAT_URL,
                  extra_args: Optional[List[str]] = None) -> subprocess.Popen:
    """用系统 Chrome 打开独立窗口（不随请求关闭）。资料目录已有 Chrome 在用时，Chrome 会把 URL 交给那个实例。"""
    if not os.path.exists(CHROME_PATH):
        raise ChromeNotFoundError(f"没有找到 Google Chrome（{CHROME_PATH}）。请先安装 Chrome；"
                                  f"装在其他位置时设置环境变量 DOUBAO_CHROME_PATH 指向 Chrome 可执行文件")
    os.makedirs(profile_path, exist_ok=True)
    return subprocess.Popen(chrome_args(profile_path, port, url, extra_args),
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)


def inject_cookies_into_chrome(port: int, cookies: list, url: str, wait_sec: float = 8.0) -> bool:
    """连接已带调试端口启动的 Chrome，把数据库里的 cookies 注入默认 context 并打开 url。

    注入的 cookie 会写回该 profile 目录；profile 本地原本缺会话（只在数据库存了 cookie）时，
    打开才能即登录。失败只记日志、返回 False，不阻断开窗。
    """
    if not cookies:
        return False
    end = time.time() + wait_sec
    while time.time() < end:
        if probe_debug_port(port):
            break
        time.sleep(0.3)
    else:
        logger.warning("注入 cookie 失败: 调试端口 %d 未就绪", port)
        return False

    from playwright.sync_api import sync_playwright
    pw = sync_playwright().start()
    try:
        browser = pw.chromium.connect_over_cdp(f"http://127.0.0.1:{port}", timeout=8000)
        if not browser.contexts:
            logger.warning("注入 cookie 失败: 端口 %d 上没有可用 context", port)
            return False
        ctx = browser.contexts[0]
        ctx.add_cookies(cookies)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=15000)
        except Exception as e:
            logger.warning("注入后导航 url 失败: %s", e)
        return True
    except Exception as e:
        logger.warning("注入 cookie 失败: %s", e)
        return False
    finally:
        pw.stop()


def probe_debug_port(port: int, timeout: float = 1.5) -> Optional[dict]:
    """GET /json/version；端口上有 Chrome 调试服务时返回版本信息，否则 None。不走代理。"""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(f"http://127.0.0.1:{port}/json/version", timeout=timeout) as resp:
            info = json.loads(resp.read().decode("utf-8"))
            return info if isinstance(info, dict) and info.get("webSocketDebuggerUrl") else None
    except Exception:
        return None


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def profile_lock_pid(profile_path: str) -> Optional[int]:
    """资料目录被 Chrome 占用时返回占用进程 pid。SingletonLock 是指向「主机名-pid」的符号链接。"""
    lock = Path(profile_path) / "SingletonLock"
    try:
        target = os.readlink(lock)
    except OSError:
        return None
    host, _, pid = target.rpartition("-")
    if not pid.isdigit():
        return None
    if host and host != socket.gethostname():
        return None  # 别的机器留下的锁，本机无法判断
    pid = int(pid)
    return pid if _pid_alive(pid) else None


# ------------------------------------------------------------------ 子进程检查
def _kill_group(proc) -> None:
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(proc.pid, sig)
        except ProcessLookupError:
            return
        for _ in range(30):
            if proc.returncode is not None:
                break
            time.sleep(0.1)
        if proc.returncode is not None:
            return


async def run_login_check(task: dict, timeout: float = CHECK_TIMEOUT_SECONDS) -> dict:
    """在独立进程组里跑 core.doubao_login_worker；超时整组杀掉（Playwright driver 收到 SIGTERM 会关掉它启动的浏览器）。"""
    env = {k: v for k, v in os.environ.items() if k.lower() not in ("http_proxy", "https_proxy", "all_proxy")}
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "core.doubao_login_worker",
        cwd=str(BACKEND_DIR), env=env, start_new_session=True,
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(json.dumps(task).encode("utf-8")), timeout)
    except asyncio.TimeoutError:
        await asyncio.get_running_loop().run_in_executor(None, _kill_group, proc)
        try:
            await asyncio.wait_for(proc.wait(), 5)
        except asyncio.TimeoutError:
            pass
        raise LoginCheckTimeout(f"检查登录超时（{int(timeout)} 秒），浏览器已关闭，请稍后重试")
    finally:
        if proc.returncode is None:
            _kill_group(proc)
    try:
        result = json.loads(out.decode("utf-8") or "{}")
    except ValueError:
        result = {}
    if not result.get("ok"):
        raise LoginCheckError(f"检查失败: {result.get('error') or '检查进程异常退出'}")
    return result


# ------------------------------------------------------------------ 检查流程
_in_flight: set = set()

PROFILE_IN_USE_MSG = ("该账号的 Chrome 窗口正开着，但不是带调试端口打开的，无法读取登录状态。"
                      "请先关闭这个账号的 Chrome 窗口再点「登录」；以后用「打开」启动的窗口可以直接检查。")


async def check_account_login(pool, account: dict, project_root: Path, url: str = DOUBAO_CHAT_URL,
                              timeout: float = CHECK_TIMEOUT_SECONDS, settle_ms: int = 5000,
                              headless: bool = False, launch_on_logout: bool = True) -> dict:
    """检查账号登录，返回 {"logged_in": bool, "message": str, "via": "cdp"|"cookies"|"profile"}。

    1. 账号的调试端口上有 Chrome（用户用「打开」/「添加」开的窗口）→ connect_over_cdp 读已有 context，只断开不关闭；
    2. 有存储 cookie → 用 cookie 起一个临时浏览器检查（不碰资料目录）；
    3. 资料目录被没有调试端口的 Chrome 占用 → 立即报 ProfileInUse；
    4. 否则用资料目录启动检查。全部带总超时，结果写回账号（cookie + last_check + 已登录时读到的会员额度 quota）。
    """
    account_id = account["id"]
    if account_id in _in_flight:
        raise LoginCheckBusy("该账号正在检查登录，请稍候")
    _in_flight.add(account_id)
    try:
        port = ensure_debug_port(pool, account)
        profile_path = str(Path(project_root) / account.get("profile_dir", ""))
        base = {"url": url, "settle_ms": settle_ms, "headless": headless}
        cookies = account.get("cookies") or []
        try:
            if probe_debug_port(port):
                via = "cdp"
                result = await run_login_check({**base, "mode": via, "cdp_endpoint": f"http://127.0.0.1:{port}"}, timeout)
            elif cookies:
                via = "cookies"
                result = await run_login_check({**base, "mode": via, "cookies": cookies}, timeout)
            else:
                if not account.get("profile_dir"):
                    raise LoginCheckError("该账号没有资料目录，也没有保存的登录态，无法检查")
                if profile_lock_pid(profile_path):
                    raise ProfileInUse(PROFILE_IN_USE_MSG)
                via = "profile"
                os.makedirs(profile_path, exist_ok=True)
                result = await run_login_check({**base, "mode": via, "profile_path": profile_path}, timeout)
        except LoginCheckError as e:
            pool.record_check(account_id, ok=False, error=str(e))
            raise

        if result.get("logged_in"):
            pool.set_cookies(account_id, result.get("cookies") or [])
            pool.record_check(account_id, ok=True)
            quota = result.get("quota")
            if quota:
                pool.set_quota(account_id, quota)
            return {"logged_in": True, "via": via, "message": "已登录，登录态已保存", "quota": quota}

        pool.set_login_state(account_id, False)
        pool.record_check(account_id, ok=True)
        if via == "cdp":
            msg = "未检测到登录，请在已打开的 Chrome 窗口里登录豆包，完成后再点「登录」"
        elif account.get("profile_dir") and profile_lock_pid(profile_path):
            raise ProfileInUse("保存的登录态已失效。" + PROFILE_IN_USE_MSG)
        else:
            if launch_on_logout and account.get("profile_dir"):
                launch_chrome(profile_path, port, url)
            msg = "未登录，已打开 Chrome，请在窗口里登录豆包，完成后再点「登录」"
        return {"logged_in": False, "via": via, "message": msg}
    finally:
        _in_flight.discard(account_id)
