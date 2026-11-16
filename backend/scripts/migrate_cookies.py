"""一次性迁移：把老 .doubao_profiles 目录里的登录 cookie 导出到数据库。
跑完后老目录缓存可清，登录态只依赖数据库里的 cookies。
"""
from pathlib import Path
from pymongo import MongoClient
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent.parent
PROFILES = ROOT / ".doubao_profiles"

c = MongoClient(__import__("os").environ["MONGODB_URL"])
db = c.dongai

accounts = list(db.doubao_accounts.find({}, {"_id": 0}))

with sync_playwright() as pw:
    for acc in accounts:
        profile_dir = acc.get("profile_dir") or ""
        if not profile_dir.startswith(".doubao_profiles"):
            print(f"[跳过] {acc['id']} 使用系统目录: {profile_dir}")
            continue
        profile_path = ROOT / profile_dir
        if not profile_path.exists():
            print(f"[缺失] {acc['id']} 目录不存在: {profile_path}")
            continue

        ctx = pw.chromium.launch_persistent_context(
            str(profile_path), channel="chrome", headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            try:
                page.goto("https://www.doubao.com/chat", timeout=20000)
                page.wait_for_timeout(2000)
            except Exception:
                pass
            cookies = ctx.cookies()
            db.doubao_accounts.update_one(
                {"id": acc["id"]},
                {"$set": {"cookies": cookies, "logged_in": True}},
            )
            print(f"[完成] {acc['id']} ({acc['name']}) 导出 {len(cookies)} 个 cookie")
        finally:
            ctx.close()

print("迁移结束")
