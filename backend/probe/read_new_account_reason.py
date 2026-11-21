"""只读探针：回读新号「无法生成视频的原因」卡片全文，不发送消息、不触发生成。

用法（cwd=backend）：
  .venv-host/bin/python -m probe.read_new_account_reason --url <chat_url> --account account_7
"""
import os
import argparse
from pathlib import Path

from playwright.sync_api import sync_playwright
from pymongo import MongoClient

BACKEND_DIR = Path(__file__).resolve().parent.parent


def load_cookies(account_id: str) -> list:
    client = MongoClient(os.environ.get("MONGODB_URL", "mongodb://localhost:27017/"))
    acc = client["dongai"]["doubao_accounts"].find_one({"id": account_id})
    return (acc.get("cookies") or []) if acc else []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--account", default="account_7")
    args = ap.parse_args()

    pw = sync_playwright().start()
    browser = pw.chromium.launch(channel="chrome", headless=False,
                                 args=["--disable-blink-features=AutomationControlled", "--disable-dev-shm-usage"])
    ctx = browser.new_context(viewport={"width": 1280, "height": 900})
    cookies = load_cookies(args.account)
    print(f"cookies={len(cookies)}")
    if cookies:
        ctx.add_cookies(cookies)
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.set_default_timeout(30000)
    page.goto(args.url, wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(4500)

    # 定位含目标文案的元素，向上取容器，打印完整文本与可点按钮
    info = page.evaluate(
        """() => {
        const target = Array.from(document.querySelectorAll('*'))
            .find(el => el.children.length <= 3 && /无法生成视频的原因|生成失败|额度|权益|实名|开通|领取|名额/.test(el.innerText||''));
        const out = {found: false, text: '', buttons: [], html: ''};
        if (!target) { out.text = document.body.innerText.slice(0, 1500); return out; }
        out.found = true;
        let node = target;
        for (let i=0;i<4 && node.parentElement;i++) node = node.parentElement;
        out.text = node.innerText || '';
        out.buttons = Array.from(node.querySelectorAll('button,a,[role=button]')).map(b => (b.innerText||'').trim()).filter(Boolean);
        out.html = node.innerHTML.slice(0, 1200);
        return out;
        }"""
    )
    print("\n===== 卡片文本 =====")
    print(info.get("text"))
    print("\n===== 按钮 =====")
    print(info.get("buttons"))
    print("\n===== 整页正文 =====")
    print(page.evaluate("() => document.body.innerText || ''")[:1800])

    browser.close()
    pw.stop()


if __name__ == "__main__":
    main()
