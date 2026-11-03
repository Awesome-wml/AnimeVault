#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""探查：坐标点模型选择器→模型列表；坐标点时长→时长选项"""
import time
from playwright.sync_api import sync_playwright

PROFILE_DIR = "/Users/dongxiangyu/Library/Application Support/Google/Chrome/Default"
VG_BTN = (489, 669)          # 底部"视频生成"
MODEL_BTN = (571, 670)       # 模型选择器"模型 Seedance 2.0 Mini"
DUR_BTN = (785, 670)         # 时长"自动·10s"

def dump(page, tag, kw=None):
    try:
        info = page.evaluate("""()=>{
            const items=[];
            document.querySelectorAll('button,div,span,[role=button],li,p,label').forEach(e=>{
                const t=(e.textContent||'').trim();
                if(t && t.length<=30) items.push(t);
            });
            return [...new Set(items)];
        }""")
        print(f"\n===== [{tag}] =====")
        if kw:
            print("匹配:", [x for x in info if any(k.lower() in x.lower() for k in kw)])
        else:
            print(info)
    except Exception as e:
        print("dump err", str(e)[:80])

with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(PROFILE_DIR, channel="chrome", headless=False,
        args=["--disable-blink-features=AutomationControlled"])
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.set_default_timeout(15000)
    page.set_viewport_size({"width":1280,"height":720})
    page.goto("https://www.doubao.com/chat", timeout=30000)
    for _ in range(300):
        if page.get_by_text("登录", exact=True).count() == 0:
            break
        time.sleep(1)
    time.sleep(4)
    print("1. 坐标点视频生成:", VG_BTN); page.mouse.click(*VG_BTN); time.sleep(5)
    dump(page, "视频生成参数区", kw=["Seedance","模型","10s","15s","16:9","比例","时长","Fast"])
    print("\n2. 坐标点模型选择器:", MODEL_BTN); page.mouse.click(*MODEL_BTN); time.sleep(4)
    dump(page, "模型面板", kw=["Seedance","Fast","2.0","Pro","Mini"])
    page.screenshot(path="/tmp/doubao_model5.png"); print("截图 /tmp/doubao_model5.png")
    # 点时长
    print("\n3. 坐标点时长:", DUR_BTN); page.mouse.click(*DUR_BTN); time.sleep(4)
    dump(page, "时长面板", kw=["10s","15s","秒","时长","自动","比例","16:9"])
    page.screenshot(path="/tmp/doubao_dur5.png"); print("截图 /tmp/doubao_dur5.png")
    time.sleep(4); ctx.close()
