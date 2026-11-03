#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""探查豆包'工作任务'功能入口：dump页面侧栏/导航的可点击功能项。只读不发送。"""
import os, time
from playwright.sync_api import sync_playwright
PROFILE_DIR = "/Users/dongxiangyu/Library/Application Support/Google/Chrome/Default"
with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(PROFILE_DIR, channel="chrome", headless=False,
        viewport={"width":1280,"height":720}, args=["--disable-blink-features=AutomationControlled"])
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.goto("https://www.doubao.com/chat", wait_until="domcontentloaded")
    time.sleep(6)
    # dump 侧栏/导航功能项
    items = page.evaluate("""()=>{
        const res=[];
        document.querySelectorAll('button,[role=button],a,[data-testid],div[class*=sidebar] div,div[class*=menu] div,div[class*=nav] div').forEach(e=>{
            const t=(e.textContent||'').trim();
            const r=e.getBoundingClientRect();
            if(!t||t.length>10||!r.width||!r.height)return;
            res.push({tag:e.tagName,text:t.slice(0,12),cls:(e.className||'').toString().slice(0,50),x:Math.round(r.x),y:Math.round(r.y)});
        });
        // 去重
        const seen=new Set(); const out=[];
        for(const x of res){const k=x.text+'|'+x.y; if(!seen.has(k)){seen.add(k);out.push(x);}}
        return out.slice(0,80);
    }""")
    for x in items:
        print(x)
    page.screenshot(path="/tmp/task_ui.png")
    print("截图: /tmp/task_ui.png")
    time.sleep(2)
    ctx.close()
