#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""探查豆包新建对话：如何选择"视频生成"模式与模型 Seedance 2.0 Fast"""
import time
from playwright.sync_api import sync_playwright

PROFILE_DIR = "/Users/dongxiangyu/Library/Application Support/Google/Chrome/Default"

def dump_ui(page, tag):
    try:
        info = page.evaluate("""()=>{
            const items=[];
            document.querySelectorAll('button,div[role=button],span,[role=tab],a').forEach(e=>{
                const t=(e.textContent||'').trim();
                if(t && t.length<=12) items.push(t);
            });
            const labels=[];
            document.querySelectorAll('[aria-label],[title],[placeholder]').forEach(e=>{
                const a=e.getAttribute('aria-label')||e.getAttribute('title')||e.getAttribute('placeholder')||'';
                if(a) labels.push(a);
            });
            return {texts:[...new Set(items)], labels:[...new Set(labels)].slice(0,60)};
        }""")
        print(f"\n===== [{tag}] 文本按钮(去重) =====")
        print(info["texts"])
        print(f"===== [{tag}] aria-label/title =====")
        print(info["labels"])
    except Exception as e:
        print("dump err", str(e)[:80])

with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(PROFILE_DIR, channel="chrome", headless=False,
        args=["--disable-blink-features=AutomationControlled"])
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.set_default_timeout(15000)
    page.goto("https://www.doubao.com/chat", timeout=30000)
    # 等登录
    for _ in range(300):
        if page.get_by_text("登录", exact=True).count() == 0:
            break
        time.sleep(1)
    time.sleep(5)
    dump_ui(page, "chat主页加载后")
    # 找含 视频/模型/生成 的元素
    try:
        hits = page.evaluate("""()=>{
            const hs=[];
            document.querySelectorAll('button,div,span,[role=tab],a,li').forEach(e=>{
                const t=(e.textContent||'').trim();
                if(/视频|模型|Seedance|生成|创作|智能体|功能/.test(t) && t.length<=20) hs.push(t);
            });
            return [...new Set(hs)];
        }""")
        print("\n===== 含[视频/模型/生成]的文本 =====")
        print(hits)
    except Exception as e:
        print("hit err", str(e)[:80])
    # 截图
    page.screenshot(path="/tmp/doubao_ui.png")
    print("\n已截图 /tmp/doubao_ui.png")
    time.sleep(8)
    ctx.close()
