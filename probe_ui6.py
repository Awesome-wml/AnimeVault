#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""探查：底部精确点模型选择器 → 看模型面板(找Seedance 2.0 Fast)"""
import time
from playwright.sync_api import sync_playwright

PROFILE_DIR = "/Users/dongxiangyu/Library/Application Support/Google/Chrome/Default"

def dump(page, tag):
    try:
        info = page.evaluate("""()=>{
            const items=[];
            document.querySelectorAll('button,div[role=button],span,[role=tab],a,li,label,div,p').forEach(e=>{
                const t=(e.textContent||'').trim();
                if(t && t.length<=30) items.push(t);
            });
            return [...new Set(items)];
        }""")
        print(f"\n===== [{tag}] =====")
        print(info)
    except Exception as e:
        print("dump err", str(e)[:80])

def click_bottom(page, match, exact=True):
    """底部区域(>70%)点击，match为文本(精确或包含)"""
    return page.evaluate("""({match,exact})=>{
        const vh=window.innerHeight; let hit=null;
        document.querySelectorAll('button,div,[role=button],span,li').forEach(e=>{
            const t=(e.textContent||'').trim();
            if(exact && t!==match) return;
            if(!exact && !t.includes(match)) return;
            const r=e.getBoundingClientRect();
            if(!r.width||!r.height) return;
            if(r.top>vh*0.60 && r.top<vh*0.98 && (!hit || r.height<hit.height)){ hit=e; }
        });
        if(hit){ hit.click(); return 'clicked:['+(hit.textContent||'').trim()+']'; }
        return 'notfound:'+match;
    }""", {"match":match,"exact":exact})

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
    print("1. 点底部'视频生成':", click_bottom(page, "视频生成"))
    time.sleep(4)
    print("2. 点模型选择器'Seedance 2.0 Mini'(底部):", click_bottom(page, "Seedance 2.0 Mini"))
    time.sleep(4)
    dump(page, "模型面板打开后")
    page.screenshot(path="/tmp/doubao_model3.png")
    print("截图 /tmp/doubao_model3.png")
    time.sleep(4)
    ctx.close()
