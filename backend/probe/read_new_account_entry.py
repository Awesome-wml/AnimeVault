"""只读探针：观察新号在豆包网页的登录身份、视频模型入口与权益/额度/实名提示。
不发送消息、不点击生成、不触发生成。

用法（cwd=backend）：
  .venv-host/bin/python -m probe.read_new_account_entry --account account_7
"""
import os
import argparse

from playwright.sync_api import sync_playwright
from pymongo import MongoClient


def load_cookies(account_id: str) -> list:
    client = MongoClient(os.environ.get("MONGODB_URL", "mongodb://localhost:27017/"))
    acc = client["dongai"]["doubao_accounts"].find_one({"id": account_id})
    return (acc.get("cookies") or []) if acc else []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--account", default="account_7")
    ap.add_argument("--url", default="https://www.doubao.com/chat/")
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
    page.wait_for_timeout(5000)

    info = page.evaluate(
        """() => {
        const txt = document.body.innerText || '';
        const kw = ['会员','额度','次数','免费','试用','实名','权益','开通','名额','受限','封禁','已用完','不足','体验券','领'];
        const lines = txt.split('\\n').map(s=>s.trim()).filter(Boolean);
        const kwLines = lines.filter(l => kw.some(k => l.includes(k)));
        const btns = Array.from(document.querySelectorAll('button,[role=button],a')).map(b=>(b.innerText||'').trim()).filter(Boolean);
        const modelBtns = btns.filter(t => /Seedance|视频|模型|创意|即梦|豆包/.test(t));
        return {url: location.href, title: document.title, kwLines: [...new Set(kwLines)].slice(0,40),
                modelBtns: [...new Set(modelBtns)].slice(0,30)};
        }"""
    )
    print("\n===== url/title =====")
    print(info["url"], "|", info["title"])
    print("\n===== 权益/额度/实名相关文案 =====")
    for l in info["kwLines"]:
        print(" -", l)
    print("\n===== 模型/视频入口按钮 =====")
    for b in info["modelBtns"]:
        print(" *", b.replace("\n", " / "))

    browser.close()
    pw.stop()


if __name__ == "__main__":
    main()
