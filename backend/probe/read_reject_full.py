"""只读探针：回读失败对话主区完整文本（排除侧边栏），定位模型拒绝文案。
不发送消息、不触发生成。

用法（cwd=backend）：
  .venv-host/bin/python -m probe.read_reject_full --url <chat_url> --account account_7
"""
import argparse

from playwright.sync_api import sync_playwright
from pymongo import MongoClient


def load_cookies(account_id: str) -> list:
    client = MongoClient("mongodb://admin:dongai_mongo_2024@localhost:27017/")
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
    page.wait_for_timeout(8000)
    try:
        page.mouse.wheel(0, 2000)
        page.wait_for_timeout(1000)
    except Exception:
        pass

    data = page.evaluate(
        """() => {
        // 侧边栏排除：aside / nav / 左侧固定宽容器
        const aside = document.querySelector('aside, [class*="sidebar"], [class*="nav-left"], [class*="side-bar"]');
        const bodyText = document.body.innerText || '';
        // 主区候选：去掉侧边栏后的长文本块
        const blocks = [];
        document.querySelectorAll('[class*="message"], [class*="bubble"], [class*="receive"], [class*="chat"], article, [data-testid*="message"]')
            .forEach(el => {
                if (aside && aside.contains(el)) return;
                const t = (el.innerText || '').trim();
                if (t && t.length > 1) blocks.push(t);
            });
        // 主区整体文本（去掉 aside 文本）
        let mainText = bodyText;
        if (aside) mainText = bodyText.replace(aside.innerText || '', '');
        return {mainText, blocks: [...new Set(blocks)].slice(0, 20)};
        }"""
    )
    print("\n===== 主区整体文本 =====")
    print(data["mainText"][:2000])
    print("\n===== 候选气泡块 =====")
    for i, b in enumerate(data["blocks"]):
        print(f"--- [{i}] len={len(b)} ---")
        print(b[:400])

    browser.close()
    pw.stop()


if __name__ == "__main__":
    main()
