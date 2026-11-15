"""
只读探针：用 account_4 cookies 打开被版权拒绝的历史对话，回读豆包回复气泡全文，
定位拦截卡片是否给出细分理由（IP/明星/素材/违规类型）。不发送任何消息、不触发生成。

用法（cwd=backend）：
  .venv-host/bin/python -m probe.read_reject_chat
  .venv-host/bin/python -m probe.read_reject_chat --url https://www.doubao.com/chat/38453984495487234
"""
import argparse
from pathlib import Path

from playwright.sync_api import sync_playwright
from pymongo import MongoClient

BACKEND_DIR = Path(__file__).resolve().parent.parent


def load_cookies(account_id: str = "account_4") -> list:
    client = MongoClient("mongodb://admin:dongai_mongo_2024@localhost:27017/")
    acc = client["dongai"]["doubao_accounts"].find_one({"id": account_id})
    return (acc.get("cookies") or []) if acc else []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="https://www.doubao.com/chat/38453984495487234")
    ap.add_argument("--account", default="account_4")
    args = ap.parse_args()

    pw = sync_playwright().start()
    browser = pw.chromium.launch(
        channel="chrome", headless=False,
        args=["--disable-blink-features=AutomationControlled", "--disable-dev-shm-usage"],
    )
    ctx = browser.new_context(viewport={"width": 1280, "height": 900})
    cookies = load_cookies(args.account)
    print(f"cookies={len(cookies)}")
    if cookies:
        ctx.add_cookies(cookies)
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.set_default_timeout(30000)
    page.goto(args.url, wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(4000)

    # 提取所有消息气泡文本（尝试常见容器）
    bubbles = page.evaluate(
        """() => {
            const out = [];
            const sels = ['[class*="message"]', '[class*="bubble"]', '[class*="chat-content"]',
                          '[class*="conversation"]', 'article', '[data-testid*="message"]'];
            const seen = new Set();
            for (const s of sels) {
                document.querySelectorAll(s).forEach(el => {
                    const t = (el.innerText || '').trim();
                    if (t && t.length > 1 && !seen.has(t)) {
                        seen.add(t);
                        out.push(t);
                    }
                });
            }
            return out;
        }"""
    )
    print(f"\n===== 命中气泡 {len(bubbles)} 段 =====\n")
    for i, b in enumerate(bubbles):
        print(f"--- [{i}] len={len(b)} ---")
        if i == 0:
            Path(BACKEND_DIR, "probe", "shot9_sent_prompt.txt").write_text(b, encoding="utf-8")
            print(b)
        else:
            print(b[:300])
        print()

    print("\n===== 整页正文（含关键词上下文）=====")
    body = page.evaluate("() => document.body.innerText || ''")
    for kw in ["版权", "限制", "违规", "违反", "明星", "角色", "相似", "侵权", "换"]:
        idx = 0
        while True:
            j = body.find(kw, idx)
            if j < 0:
                break
            print(f"[{kw}] …{body[max(0,j-40):j+60]}…")
            idx = j + 1

    browser.close()
    pw.stop()


if __name__ == "__main__":
    main()
