"""
豆包登录检查子进程（由 core.doubao_chrome.run_login_check 启动，不要直接在请求线程里调用）。

stdin 读一份 JSON 任务，stdout 写一份 JSON 结果：
  任务 {"mode": "cdp"|"cookies"|"profile", "url": ..., "settle_ms": 5000, "headless": false,
        "cdp_endpoint": "http://127.0.0.1:<port>"   # mode=cdp
        "cookies": [...]                             # mode=cookies
        "profile_path": "/abs/path"                  # mode=profile
        "executable_path": 可选，默认用 channel=chrome}
  结果 {"ok": true, "logged_in": bool, "cookies": [...]} 或 {"ok": false, "error": "..."}

放在独立进程里跑，是为了让调用方能设总超时：超时直接杀掉整个进程组（含 Playwright driver），
不会有挂住的线程占着线程池。
mode=cdp 连的是用户自己开着的 Chrome：只新开一个标签页检查后关掉，绝不关闭用户的窗口或浏览器。
"""
import json
import sys

from playwright.sync_api import sync_playwright

LAUNCH_ARGS = ["--disable-blink-features=AutomationControlled", "--disable-dev-shm-usage"]
VIEWPORT = {"width": 1280, "height": 800}


def is_logged_in(page, url: str, settle_ms: int) -> bool:
    """沿用原判断：打开豆包页面，等页面渲染后没有「登录」按钮即视为已登录。"""
    page.goto(url, wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(settle_ms)
    return page.query_selector('button:has-text("登录")') is None


def _launch_kwargs(task: dict) -> dict:
    kw = {"headless": bool(task.get("headless")), "args": LAUNCH_ARGS, "timeout": 30000}
    if task.get("executable_path"):
        kw["executable_path"] = task["executable_path"]
    else:
        kw["channel"] = "chrome"
    return kw


def _check_cdp(pw, task: dict) -> dict:
    browser = pw.chromium.connect_over_cdp(task["cdp_endpoint"], timeout=10000)
    if not browser.contexts:
        raise RuntimeError("调试端口上的 Chrome 没有可用的窗口")
    ctx = browser.contexts[0]
    page = ctx.new_page()  # 在用户已有的 context 里开一个新标签页
    try:
        logged_in = is_logged_in(page, task["url"], task["settle_ms"])
        cookies = ctx.cookies() if logged_in else []
    finally:
        try:
            page.close()  # 只关自己开的标签页
        except Exception:
            pass
    # 不调用 browser.close()：由 pw.stop() 断开连接，用户的 Chrome 保持原样
    return {"ok": True, "logged_in": logged_in, "cookies": cookies}


def _check_cookies(pw, task: dict) -> dict:
    browser = pw.chromium.launch(**_launch_kwargs(task))
    try:
        ctx = browser.new_context(viewport=VIEWPORT)
        ctx.add_cookies(task.get("cookies") or [])
        page = ctx.new_page()
        logged_in = is_logged_in(page, task["url"], task["settle_ms"])
        return {"ok": True, "logged_in": logged_in, "cookies": ctx.cookies() if logged_in else []}
    finally:
        browser.close()


def _check_profile(pw, task: dict) -> dict:
    ctx = pw.chromium.launch_persistent_context(task["profile_path"], viewport=VIEWPORT, **_launch_kwargs(task))
    try:
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        logged_in = is_logged_in(page, task["url"], task["settle_ms"])
        return {"ok": True, "logged_in": logged_in, "cookies": ctx.cookies() if logged_in else []}
    finally:
        ctx.close()


MODES = {"cdp": _check_cdp, "cookies": _check_cookies, "profile": _check_profile}


def run(task: dict) -> dict:
    fn = MODES.get(task.get("mode"))
    if fn is None:
        return {"ok": False, "error": f"未知检查方式: {task.get('mode')!r}"}
    task.setdefault("settle_ms", 5000)
    pw = sync_playwright().start()
    try:
        return fn(pw, task)
    finally:
        pw.stop()


def main():
    try:
        result = run(json.load(sys.stdin))
    except Exception as e:  # 任何异常都以 JSON 返回，调用方统一处理
        result = {"ok": False, "error": f"{type(e).__name__}: {e}"}
    sys.stdout.write(json.dumps(result, ensure_ascii=False))
    sys.stdout.flush()


if __name__ == "__main__":
    main()
