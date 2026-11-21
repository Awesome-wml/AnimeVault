"""
独立验证探针：跑业务类 DoubaoVideoGenerator.upload_images，确认新的 expect_response
等待逻辑在真实登录态下能抓到 StoreUri。只读 + 上传测试图，不发送提示词、不触发生成。

用法（cwd=backend）：
  .venv-host/bin/python -m probe.verify_upload_expect
"""
import os
import logging
from pathlib import Path

from playwright.sync_api import sync_playwright
from pymongo import MongoClient

from core.doubao_automation import DoubaoVideoGenerator
from utils.file_util import FileUtil

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("verify")

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BACKEND_DIR.parent


def load_cookies(account_id: str = "account_1") -> list:
    client = MongoClient(os.environ.get("MONGODB_URL", "mongodb://localhost:27017/"))
    acc = client["dongai"]["doubao_accounts"].find_one({"id": account_id})
    return (acc.get("cookies") or []) if acc else []


def main():
    imgs = sorted(FileUtil.get_images_dir().glob("*.png"))[:3]
    log.info("测试图 %d 张: %s", len(imgs), [p.name for p in imgs])

    pw = sync_playwright().start()
    browser = pw.chromium.launch(
        channel="chrome", headless=False,
        args=["--disable-blink-features=AutomationControlled", "--disable-dev-shm-usage"],
    )
    ctx = browser.new_context(viewport={"width": 1280, "height": 800})
    cookies = load_cookies()
    if cookies:
        ctx.add_cookies(cookies)
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.set_default_timeout(30000)
    page.goto("https://www.doubao.com/chat/", wait_until="domcontentloaded", timeout=30000)
    page.wait_for_selector('[contenteditable=true]', timeout=10000)

    gen = DoubaoVideoGenerator(str(PROJECT_ROOT))
    gen.context = ctx
    uris = gen.upload_images(page, [str(p) for p in imgs])

    log.info("=== 最终 captured %d 条 ===", len(uris))
    for u in uris:
        log.info("  %s", u)

    browser.close()
    pw.stop()


if __name__ == "__main__":
    main()
