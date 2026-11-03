#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""探查：视频生成参数选择能否稳定完成(Seedance 2.0 Fast/15s/16:9)，不发视频"""
import time
from playwright.sync_api import sync_playwright

PROFILE_DIR = "/Users/dongxiangyu/Library/Application Support/Google/Chrome/Default"
VG_BTN=(489,669); MODEL_BTN=(571,670); DUR_BTN=(785,670)

def dump(page, tag):
    try:
        info = page.evaluate("""()=>{const items=[];
            document.querySelectorAll('button,div,span,[role=button],li,p,label').forEach(e=>{const t=(e.textContent||'').trim(); if(t&&t.length<=30) items.push(t);});
            return [...new Set(items)];}""")
        print(f"[{tag}] 相关:", [x for x in info if any(k in x for k in ["Seedance","模型","10s","15s","16:9","时长","比例","自动"])])
    except Exception as e:
        print(f"[{tag}] err {str(e)[:60]}")

def dom_click(page, match):
    return page.evaluate("""(match)=>{const vh=window.innerHeight;let hit=null;
        document.querySelectorAll('button,div,[role=button],span,li').forEach(e=>{
            const t=(e.textContent||'').trim(); if(t!==match) return;
            const r=e.getBoundingClientRect(); if(!r.width||!r.height) return;
            if(r.top<vh*0.50) return;
            if(!hit||r.height<hit.height) hit=e;});
        if(hit){hit.click();return 'ok:'+match;}return 'miss:'+match;}""", match)

with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(PROFILE_DIR, channel="chrome", headless=False,
        args=["--disable-blink-features=AutomationControlled"])
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.set_default_timeout(12000)
    page.set_viewport_size({"width":1280,"height":720})
    page.goto("https://www.doubao.com/chat", timeout=30000)
    for _ in range(300):
        if page.get_by_text("登录", exact=True).count() == 0: break
        time.sleep(1)
    time.sleep(3)
    print("点视频生成"); page.mouse.click(*VG_BTN); time.sleep(5)
    dump(page, "视频生成")
    print("点模型"); page.mouse.click(*MODEL_BTN); time.sleep(3)
    dump(page, "模型面板")
    print("选Fast:", dom_click(page, "Seedance 2.0 Fast")); time.sleep(2)
    page.keyboard.press("Escape"); time.sleep(1)
    dump(page, "选Fast后")
    print("点时长"); page.mouse.click(*DUR_BTN); time.sleep(3)
    dump(page, "时长面板")
    print("选15s:", dom_click(page, "15s")); time.sleep(2)
    dump(page, "选15s后(看16:9是否还在)")
    print("选16:9:", dom_click(page, "16:9")); time.sleep(2)
    dump(page, "选16:9后")
    page.keyboard.press("Escape"); time.sleep(1)
    dump(page, "ESC后")
    page.screenshot(path="/tmp/doubao_param.png")
    print("截图 /tmp/doubao_param.png")
    time.sleep(3); ctx.close()
