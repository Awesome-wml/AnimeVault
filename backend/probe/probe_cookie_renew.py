"""只读探针：豆包登录 cookie 会不会续期、是哪个接口续的。

做三件事，都不发消息、不触发生成：
1. 打印账号现在存的核心会话 cookie 的到期时间，并解开 sid_guard（会话签发时间 + 有效期）；
2. 用这份 cookie 打开豆包，记下页面自己发出的请求里，哪些响应下发了会话 cookie（Set-Cookie）；
3. 逐个主动请求几个候选接口（--try 可追加），看哪个会下发新的会话 cookie。
最后对比打开前后各 cookie 的到期时间。只有加 --save 才把新 cookie 写回数据库。

候选接口是按字节系通行证的常见路径猜的，没有官方文档；探针的目的就是在真实账号上确认。
输出里只有 cookie 名、到期时间和接口路径，不打印 cookie 的值。

用法（cwd=backend）：
  .venv-host/bin/python -m probe.probe_cookie_renew --account account_7
  .venv-host/bin/python -m probe.probe_cookie_renew --account account_7 --try /passport/xxx/ --save
"""
import argparse
import os
import time
from datetime import datetime
from http.cookies import SimpleCookie
from urllib.parse import unquote, urlsplit

from playwright.sync_api import sync_playwright
from pymongo import MongoClient

SESSION_COOKIES = {
    "sessionid", "sessionid_ss", "sid_tt", "uid_tt", "uid_tt_ss", "sid_guard", "sid_ucp_v1", "ssid_ucp_v1",
    "passport_auth_status", "passport_auth_status_ss",
}
# 豆包网页端的应用编号；通行证接口一般要带
AID = "497858"
CANDIDATES = [
    f"/passport/web/account/info/?aid={AID}&account_sdk_source=web",
    f"/passport/account/info/v2/?aid={AID}&account_sdk_source=web",
    f"/passport/web/user/info/?aid={AID}&account_sdk_source=web",
]


def _collection():
    client = MongoClient(os.environ.get("MONGODB_URL", "mongodb://localhost:27017/"))
    return client[os.environ.get("MONGODB_DB_NAME", "dongai")]["doubao_accounts"]


def _days(exp) -> str:
    if not exp or exp <= 0:
        return "会话级（无到期时间）"
    return f"{datetime.fromtimestamp(exp):%Y-%m-%d %H:%M}（还剩 {(exp - time.time()) / 86400:.1f} 天）"


def decode_sid_guard(value: str) -> str:
    """sid_guard = 会话ID|签发时间戳|有效期秒数|到期日期。返回可读的一行；格式不对返回空串。"""
    parts = unquote(value or "").split("|")
    if len(parts) < 3 or not parts[1].isdigit() or not parts[2].isdigit():
        return ""
    issued, life = int(parts[1]), int(parts[2])
    return (f"签发于 {datetime.fromtimestamp(issued):%Y-%m-%d %H:%M}，有效期 {life / 86400:.0f} 天，"
            f"到 {datetime.fromtimestamp(issued + life):%Y-%m-%d %H:%M}")


def snapshot(cookies: list) -> dict:
    return {c["name"]: c for c in cookies if c.get("name") in SESSION_COOKIES and "doubao" in (c.get("domain") or "")}


def show(title: str, snap: dict) -> None:
    print(f"\n===== {title} =====")
    if not snap:
        print("  （没有会话 cookie）")
    for name in sorted(snap):
        print(f"  {name:28s} {_days(snap[name].get('expires'))}")
    guard = decode_sid_guard((snap.get("sid_guard") or {}).get("value", ""))
    if guard:
        print(f"  sid_guard 内容：{guard}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--account", required=True)
    ap.add_argument("--url", default="https://www.doubao.com/chat/")
    ap.add_argument("--try", dest="extra", action="append", default=[], help="追加要试的接口路径（可多次）")
    ap.add_argument("--save", action="store_true", help="把打开后的最新 cookie 写回数据库")
    ap.add_argument("--headless", action="store_true")
    args = ap.parse_args()

    col = _collection()
    acc = col.find_one({"id": args.account})
    cookies = (acc or {}).get("cookies") or []
    if not cookies:
        raise SystemExit(f"账号 {args.account} 没有保存的 cookie")
    before = snapshot(cookies)
    show("数据库里现在的会话 cookie", before)

    issued = []   # [(阶段, 接口路径, cookie 名, 到期说明)]
    stage = {"name": "页面自己发的请求"}

    def on_response(resp):
        try:
            headers = resp.headers_array()
        except Exception:
            return
        for h in headers:
            if h["name"].lower() != "set-cookie":
                continue
            jar = SimpleCookie()
            try:
                jar.load(h["value"])
            except Exception:
                continue
            for name, morsel in jar.items():
                if name in SESSION_COOKIES:
                    life = morsel["max-age"] or morsel["expires"] or "会话级"
                    u = urlsplit(resp.url)
                    issued.append((stage["name"], f"{resp.request.method} {u.netloc}{u.path}", name, str(life)))

    pw = sync_playwright().start()
    browser = pw.chromium.launch(channel="chrome", headless=args.headless,
                                 args=["--disable-blink-features=AutomationControlled", "--disable-dev-shm-usage"])
    try:
        ctx = browser.new_context(viewport={"width": 1280, "height": 900})
        ctx.add_cookies(cookies)
        ctx.on("response", on_response)
        page = ctx.new_page()
        page.goto(args.url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(8000)
        if page.query_selector('button:has-text("登录")') is not None:
            raise SystemExit("这份 cookie 已经是未登录状态，无法测续期；请先重新登录这个账号")

        print("\n===== 主动请求候选接口 =====")
        for path in CANDIDATES + args.extra:
            stage["name"] = f"主动请求 {path.split('?')[0]}"
            n = len(issued)
            try:
                res = page.evaluate(
                    """async (p) => { const r = await fetch(p, {credentials: 'include'});
                                      return {status: r.status, body: (await r.text()).slice(0, 120)}; }""", path)
            except Exception as e:
                res = {"status": "请求失败", "body": str(e)[:120]}
            page.wait_for_timeout(1500)
            got = sorted({x[2] for x in issued[n:]})
            print(f"  {path.split('?')[0]:38s} 状态 {res['status']}，下发会话 cookie：{'、'.join(got) or '无'}")
            print(f"      返回开头：{res['body']!r}")

        after_all = ctx.cookies()
        after = snapshot(after_all)
    finally:
        browser.close()
        pw.stop()

    print("\n===== 哪些响应下发了会话 cookie =====")
    if not issued:
        print("  没有任何响应下发会话 cookie")
    for st, url, name, life in issued:
        print(f"  [{st}] {url}  →  {name}（Max-Age/Expires：{life}）")

    show("打开豆包之后的会话 cookie", after)
    print("\n===== 结论 =====")
    extended = [n for n in after if (after[n].get("expires") or 0) > (before.get(n, {}).get("expires") or 0) + 3600]
    if extended:
        print(f"  到期时间变晚了：{'、'.join(sorted(extended))} —— 会续期，接口见上面的列表")
    else:
        print("  所有会话 cookie 的到期时间都没变 —— 这次访问和候选接口都没有续期")
    if args.save:
        col.update_one({"id": args.account}, {"$set": {"cookies": after_all}})
        print("  已把最新 cookie 写回数据库")


if __name__ == "__main__":
    main()
