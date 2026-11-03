#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""探查：底部限定点视频生成 → 点模型选择器 → 看Seedance模型面板"""
import time
from playwright.sync_api import sync_playwright

PROFILE_DIR = "/Users/dongxiangyu/Library/Application Support/Google/Chrome/Default"

def dump(page, tag):
    try:
        info = page.evaluate("""()=>{
            const items=[];
            document.querySelectorAll('button,div[role=button],span,[role=tab],a,li,label,div').forEach(e=>{
                const t=(e.textContent||'').trim();
                if(t && t.length<=28) items.push(t);
            });
            return [...new Set(items)];
        }""")
        print(f"\n===== [{tag}] 文本 =====")
        print(info)
    except Exception as e:
        print("dump err", str(e)[:80])

def click_bottom_btn(page, text):
    return page.evaluate("""(text)=>{
        const vh=window.innerHeight; let hit=null;
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

def click_contains(page, keyword):
    return page.evaluate("""(kw)=>{
        let hit=null;
        document.querySelectorAll('button,div,[role=button],span,li').forEach(e=>{
            const t=(e.textContent||'').trim();
            if(t.includes(kw) && !hit){ hit=e; }
        });
        if(hit){ hit.click(); return 'clicked:'+hit.textContent.trim(); }
        return 'notfound:'+kw;
    }""", keyword)

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
    print("1. 点底部视频生成:", click_bottom_btn(page, "视频生成"))
    time.sleep(4)
    dump(page, "视频生成参数区")
    # 找含 Seedance / 模型 的元素
    print("\n2. 点击含'Seedance'的元素(模型选择器):", click_contains(page, "Seedance"))
    time.sleep(4)
    dump(page, "模型面板")
    page.screenshot(path="/tmp/doubao_model2.png")
    print("截图 /tmp/doubao_model2.png")
    time.sleep(4)
    ctx.close()
