"""
探针：对比两种输入注入方式，确认豆包编辑器在哪条路径下把 attachment:// 标记
解析成附件芯片（高亮实体节点），而不是裸露纯文本。只读观察，不发送。

用法（cwd=backend）：
  .venv-host/bin/python -m probe.verify_paste_inject
"""
import os
import logging
from pathlib import Path

from playwright.sync_api import sync_playwright
from pymongo import MongoClient

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("verify-paste")

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BACKEND_DIR.parent

URI = "tos-cn-i-a9rns2rl98/3588de76112f46e6b4f08abee52e5282.png"
TEXT = (
    "背景为廊外云海，缓缓推近，[赵丙谦](attachment://" + URI + "?type=1)"
    "面朝[李川](attachment://" + URI + "?type=1)方向，眉头紧锁。"
)

DUMP_JS = """() => {
  const ed = document.querySelector('[contenteditable=true]');
  if (!ed) return null;
  const chips = [...ed.querySelectorAll('img,a,span,div')]
    .filter(n => /attach|image|chip|mention|pill|tag|preview|card/i.test(n.className || ''))
    .map(n => ({ tag: n.tagName, cls: (n.className || '').slice(0, 80),
                 html: n.outerHTML.slice(0, 220) }));
  return { text: (ed.innerText || '').slice(0, 300),
           imgs: ed.querySelectorAll('img').length,
           chips, html: (ed.innerHTML || '').slice(0, 1500) };
}"""

CLEAR_JS = """() => {
  const ed = document.querySelector('[contenteditable=true]');
  if (ed) { ed.focus(); ed.innerHTML = ''; }
}"""


def load_cookies(account_id="account_1"):
    client = MongoClient(os.environ.get("MONGODB_URL", "mongodb://localhost:27017/"))
    acc = client["dongai"]["doubao_accounts"].find_one({"id": account_id})
    return (acc.get("cookies") or []) if acc else []


def dump(tag, page):
    page.wait_for_timeout(800)
    r = page.evaluate(DUMP_JS)
    log.info("=== [%s] ===", tag)
    if not r:
        log.info("  无输入框"); return
    log.info("  imgs=%d chips=%d", r["imgs"], len(r["chips"]))
    for c in r["chips"]:
        log.info("  chip %s %s", c["tag"], c["cls"])
        log.info("    %s", c["html"])
    log.info("  text: %s", r["text"])
    log.info("  html: %s", r["html"])


def main():
    pw = sync_playwright().start()
    browser = pw.chromium.launch(
        channel="chrome", headless=False,
        args=["--disable-blink-features=AutomationControlled", "--disable-dev-shm-usage"],
    )
    ctx = browser.new_context(viewport={"width": 1280, "height": 800})
    ctx.grant_permissions(["clipboard-read", "clipboard-write"])
    cookies = load_cookies()
    if cookies:
        ctx.add_cookies(cookies)
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.set_default_timeout(30000)
    page.goto("https://www.doubao.com/chat/", wait_until="domcontentloaded", timeout=30000)
    page.wait_for_selector('[contenteditable=true]', timeout=10000)

    # 方式 A：execCommand insertText（现状）
    page.evaluate("""(text) => {
        const ed = document.querySelector('[contenteditable=true]');
        if (ed) { ed.focus(); document.execCommand('insertText', false, text); }
    }""", TEXT)
    dump("A insertText", page)

    page.evaluate(CLEAR_JS)

    # 方式 B1：剪贴板写入 + Cmd+V 真实粘贴
    page.evaluate("(t) => navigator.clipboard.writeText(t)", TEXT)
    page.wait_for_timeout(300)
    page.keyboard.press("Meta+V")
    dump("B1 clipboard+CmdV", page)

    browser.close()
    pw.stop()


if __name__ == "__main__":
    main()
