#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""稳定版：坐标点底部视频生成 → 定位点模型选择器 → 看Seedance模型面板"""
import time
from playwright.sync_api import sync_playwright

PROFILE_DIR = "/Users/dongxiangyu/Library/Application Support/Google/Chrome/Default"
VG_BTN = (489, 669)   # 底部"视频生成"按钮坐标(viewport 1280x720)

def dump(page, tag, contains=None):
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
        if contains:
            print("匹配关键词:", [x for x in info if contains.lower() in x.lower()])
        print(info)
    except Exception as e:
        print("dump err", str(e)[:80])

def dom_click(page, match, bottom_only=True):
    return page.evaluate("""({match,bottom})=>{
        const vh=window.innerHeight; let hit=null;
        document.querySelectorAll('button,div,[role=button],span,li').forEach(e=>{
            const t=(e.textContent||'').trim();
            if(t!==match) return;
            const r=e.getBoundingClientRect();
            if(!r.width||!r.height) return;
            if(bottom && r.top<vh*0.60) return;
            if(!hit || r.height<hit.height) hit=e;
        });
        if(hit){ hit.click(); return 'clicked:['+(hit.textContent||'').trim()+']'; }
        return 'notfound:'+match;
    }""", {"match":match,"bottom":bottom_only})

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
    print("1. 坐标点底部'视频生成'按钮:", VG_BTN)
    page.mouse.click(VG_BTN[0], VG_BTN[1])
    time.sleep(5)
    dump(page, "点视频生成后(找Seedance)")
    # 点模型选择器
    print("\n2. 点模型选择器:", dom_click(page, "Seedance 2.0 Mini", True))
    time.sleep(4)
    dump(page, "模型面板(找Seedance 2.0 Fast/模型列表)")
    page.screenshot(path="/tmp/doubao_model4.png")
    print("截图 /tmp/doubao_model4.png")
    time.sleep(4)
    ctx.close()
