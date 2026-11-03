#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""探查'新工作任务'点击后的界面：任务如何发视频/置顶。不发送视频。"""
import os, time
from playwright.sync_api import sync_playwright
PROFILE_DIR = "/Users/dongxiangyu/Library/Application Support/Google/Chrome/Default"
with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(PROFILE_DIR, channel="chrome", headless=False,
        viewport={"width":1280,"height":720}, args=["--disable-blink-features=AutomationControlled"])
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.goto("https://www.doubao.com/chat", wait_until="domcontentloaded")
    time.sleep(6)
    # 点"新工作任务"
    r = page.evaluate("""()=>{const els=[...document.querySelectorAll('div,button')];
        const e=els.find(e=>{const t=(e.textContent||'').trim();return t.startsWith('新工作任务');});
        if(e){e.click();return 'clicked';}return 'notfound';}""")
    print("点新工作任务:", r)
    time.sleep(5)
    page.screenshot(path="/tmp/task_new.png")
    # dump 界面
    txt = page.evaluate("()=>document.body.innerText.slice(0,1500)")
    print("=== 界面文本 ===\n", txt)
    print("URL:", page.url)
    time.sleep(2)
    ctx.close()
