#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""探查豆包视频生成界面：点'视频生成'后如何选模型/上传/发送"""
import time
from playwright.sync_api import sync_playwright

PROFILE_DIR = "/Users/dongxiangyu/Library/Application Support/Google/Chrome/Default"

def dump(page, tag):
    try:
        info = page.evaluate("""()=>{
            const items=[];
            document.querySelectorAll('button,div[role=button],span,[role=tab],a,li,label').forEach(e=>{
                const t=(e.textContent||'').trim();
                if(t && t.length<=16) items.push(t);
            });
            const labels=[];
            document.querySelectorAll('[aria-label],[title],[placeholder]').forEach(e=>{
                const a=e.getAttribute('aria-label')||e.getAttribute('title')||e.getAttribute('placeholder')||'';
                if(a) labels.push(a);
            });
            return {texts:[...new Set(items)], labels:[...new Set(labels)].slice(0,80)};
        }""")
        print(f"\n===== [{tag}] 文本按钮 =====")
        print(info["texts"])
        print(f"===== [{tag}] aria/title/placeholder =====")
        print(info["labels"])
    except Exception as e:
        print("dump err", str(e)[:80])

with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(PROFILE_DIR, channel="chrome", headless=False,
        args=["--disable-blink-features=AutomationControlled"])
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.set_default_timeout(15000)
    page.goto("https://www.doubao.com/chat", timeout=30000)
    for _ in range(300):
        if page.get_by_text("登录", exact=True).count() == 0:
            break
        time.sleep(1)
    time.sleep(3)
    print("点击'视频生成'入口…")
    clicked = False
    try:
        page.eval_on_selector_all("button,div,[role=tab],span,a,li","els=>{for(const e of els){if((e.textContent||'').trim()==='视频生成'){e.click();return;}}}")
        clicked = True
    except Exception as e:
        print("click err", str(e)[:80])
    print("clicked:", clicked)
    # 等待界面切换
    time.sleep(5)
    print("pages count:", len(ctx.pages))
    for i, pg in enumerate(ctx.pages):
        print(f"  page{i} url={pg.url}")
    dump(page, "点击视频生成后")
    page.screenshot(path="/tmp/doubao_video_ui.png")
    print("已截图 /tmp/doubao_video_ui.png")
    time.sleep(6)
    ctx.close()
