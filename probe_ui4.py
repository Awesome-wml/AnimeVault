#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""探查：点开模型选择面板，看Seedance模型选项 + 时长/比例设置"""
import time
from playwright.sync_api import sync_playwright

PROFILE_DIR = "/Users/dongxiangyu/Library/Application Support/Google/Chrome/Default"

def dump(page, tag):
    try:
        info = page.evaluate("""()=>{
            const items=[];
            document.querySelectorAll('button,div[role=button],span,[role=tab],a,li,label,div').forEach(e=>{
                const t=(e.textContent||'').trim();
                if(t && t.length<=24) items.push(t);
            });
            return [...new Set(items)];
        }""")
        print(f"\n===== [{tag}] 文本 =====")
        print(info)
    except Exception as e:
        print("dump err", str(e)[:80])

def click_text(page, text, area=None):
    """点击含指定文本的元素"""
    return page.evaluate("""(text)=>{
        let hit=null;
        document.querySelectorAll('button,div,[role=button],span,li,[role=tab]').forEach(e=>{
            const t=(e.textContent||'').trim();
            if(t===text && !hit){ hit=e; }
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
    print("1. 点底部视频生成:", click_text(page, "视频生成"))
    time.sleep(4)
    dump(page, "视频生成模式")
    print("\n2. 点模型选择器(Seedance 2.0 Mini):", click_text(page, "模型 Seedance 2.0 Mini"))
    time.sleep(4)
    dump(page, "模型面板打开后")
    page.screenshot(path="/tmp/doubao_model.png")
    print("截图 /tmp/doubao_model.png")
    time.sleep(4)
    ctx.close()
