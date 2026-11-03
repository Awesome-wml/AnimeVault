#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""探查豆包'新工作任务'创建多个任务后是否并行：连续创建任务，dump左侧任务列表。不发送视频。"""
import os, time
from playwright.sync_api import sync_playwright
PROFILE_DIR = "/Users/dongxiangyu/Library/Application Support/Google/Chrome/Default"
with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(PROFILE_DIR, channel="chrome", headless=False,
        viewport={"width":1280,"height":720}, args=["--disable-blink-features=AutomationControlled"])
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.goto("https://www.doubao.com/chat", wait_until="domcontentloaded")
    time.sleep(6)
    def click_new_task():
        return page.evaluate("""()=>{const els=[...document.querySelectorAll('div,button,[role=button]')];
            const e=els.find(e=>{const t=(e.textContent||'').trim();return t.startsWith('新工作任务');});
            if(e){e.click();return 'clicked';}return 'notfound';}""")
    def dump_sidebar():
        return page.evaluate("""()=>{
            const res=[];
            document.querySelectorAll('[class*=sidebar] div,aside div,div[class*=nav] div').forEach(e=>{
                const t=(e.textContent||'').trim();
                const r=e.getBoundingClientRect();
                if(!t||t.length>18||!r.width||!r.height||r.x>320)return;
                res.push({t:t.slice(0,16),y:Math.round(r.y)});
            });
            const seen=new Set();const out=[];
            for(const x of res){const k=x.t+'|'+x.y;if(!seen.has(k)){seen.add(k);out.push(x);}}
            return out.slice(0,50);
        }""")
    print("== 初始侧栏 ==")
    for x in dump_sidebar(): print(x)
    for i in range(3):
        print(f"== 创建任务{i+1} ==")
        print("点击:", click_new_task()); time.sleep(4)
        for x in dump_sidebar(): print(x)
    page.screenshot(path="/tmp/task_multi.png")
    print("截图: /tmp/task_multi.png  URL:", page.url)
    time.sleep(2)
    ctx.close()
