"""回归：uvicorn 默认 uvloop 时，线程池里的 Playwright 同步 API 启动浏览器会挂住。

main._reset_loop_policy_for_threads() 在 lifespan 里把全局策略换回标准 asyncio，
之后线程里新建的循环能正常启动浏览器。
"""
import asyncio
import os
import shutil

import pytest

uvloop = pytest.importorskip("uvloop")

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


@pytest.mark.skipif(not os.path.exists(CHROME) and not shutil.which("google-chrome"),
                    reason="本机没有 Chrome")
def test_playwright_in_threadpool_after_policy_reset():
    from starlette.concurrency import run_in_threadpool
    from playwright.sync_api import sync_playwright
    import main

    def launch():
        p = sync_playwright().start()
        try:
            b = p.chromium.launch(channel="chrome", headless=True, timeout=30000)
            b.close()
            return True
        finally:
            p.stop()

    async def run():
        main._reset_loop_policy_for_threads()
        return await asyncio.wait_for(run_in_threadpool(launch), timeout=40)

    old = asyncio.get_event_loop_policy()
    try:
        asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
        loop = asyncio.new_event_loop()          # 模拟 uvicorn：主循环是 uvloop
        try:
            assert loop.run_until_complete(run()) is True
        finally:
            loop.close()
        assert not type(asyncio.get_event_loop_policy()).__module__.startswith("uvloop")
    finally:
        asyncio.set_event_loop_policy(old)
