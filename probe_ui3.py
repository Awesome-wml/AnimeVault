#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""探查：点底部'视频生成'按钮 → 选模型Seedance → 找上传/发送界面"""
import time
from playwright.sync_api import sync_playwright

PROFILE_DIR = "/Users/dongxiangyu/Library/Application Support/Google/Chrome/Default"

def dump(page, tag):
    try:
        info = page.evaluate("""()=>{
            const items=[];
            document.querySelectorAll('button,div[role=button],span,[role=tab],a,li,label').forEach(e=>{
                const t=(e.textContent||'').trim();
                if(t && t.length<=20) items.push(t);
            });
            const labels=[];
            document.querySelectorAll('[aria-label],[title],[placeholder]').forEach(e=>{
                const a=e.getAttribute('aria-label')||e.getAttribute('title')||e.getAttribute('placeholder')||'';
                if(a) labels.push(a);
            });
            return {texts:[...new Set(items)], labels:[...new Set(labels)].slice(0,100)};
        }""")
        print(f"\n===== [{tag}] 文本按钮 =====")
        print(info["texts"])
        print(f"===== [{tag}] aria/title/placeholder =====")
        print(info["labels"])
    except Exception as e:
        print("dump err", str(e)[:80])

def click_bottom_btn(page, text):
    """精准点击页面底部（>75%高度）的功能按钮"""
    return page.evaluate("""(text)=>{
        const vh=window.innerHeight;
        let hit=null;
        document.querySelectorAll('button,div,[role=button],span,li').forEach(e=>{
            const t=(e.textContent||'').trim();
            if(t!==text) return;
            const r=e.getBoundingClientRect();
            if(!r.width||!r.height) return;
            if(r.top>vh*0.70 && r.top<vh*0.97){ hit=e; }
        });
        if(hit){ hit.click(); return 'clicked:'+text; }
        return 'notfound:'+text;
    }""", text)

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
    print("点击底部'视频生成':", click_bottom_btn(page, "视频生成"))
    time.sleep(5)
    dump(page, "点底部视频生成后")
    page.screenshot(path="/tmp/doubao_vg.png")
    print("截图 /tmp/doubao_vg.png")
    time.sleep(5)
    ctx.close()
