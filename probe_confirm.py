#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""探查豆包"视频生成参数确认"消息的真实UI，找正确的确认方式（按钮/快捷回复）。不点确认不扣额度。"""
import sys, os, time
from playwright.sync_api import sync_playwright

PROFILE_DIR = "/Users/dongxiangyu/Library/Application Support/Google/Chrome/Default"
VG_BTN=(489,669); MODEL_BTN=(571,670)

with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(
        PROFILE_DIR, channel="chrome", headless=False,
        viewport={"width":1280,"height":720}, args=["--disable-blink-features=AutomationControlled"],
    )
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.goto("https://www.doubao.com/chat/38451289936088322", wait_until="domcontentloaded")
    time.sleep(3)
    # 进视频生成模式+选Fast
    page.mouse.click(*VG_BTN); time.sleep(5)
    page.mouse.click(*MODEL_BTN); time.sleep(3)
    r = page.evaluate("""()=>{const vh=window.innerHeight;let hit=null;
        document.querySelectorAll('button,div,[role=button],span,li').forEach(e=>{
            const t=(e.textContent||'').trim();
            if(t!=='Seedance 2.0 Fast')return;
            const r=e.getBoundingClientRect(); if(!r.width||!r.height)return;
            if(r.top<vh*0.60)return;
            if(!hit||r.height<hit.height)hit=e;});
        if(hit){hit.click();return 'clicked';}return 'notfound';}""")
    print("选模型:", r); time.sleep(2)
    page.keyboard.press("Escape"); time.sleep(1)
    # 发一条简单提示词（触发确认）
    ed = page.locator("[contenteditable=true]").first
    ed.click(); time.sleep(0.5)
    page.evaluate("""()=>{const ed=document.querySelector('[contenteditable=true]');ed.focus();document.execCommand('insertText',false,'生成一段15秒测试视频，只验证参数确认流程');}""")
    time.sleep(0.5); ed.press("Enter"); time.sleep(1)
    try:
        page.eval_on_selector_all("button","els=>{for(const e of els){if((e.textContent||'').trim()==='↑'||e.getAttribute('aria-label')==='发送'){e.click();break;}}}")
    except Exception: pass
    print("已发送测试提示词，等待豆包确认消息…")
    # 等确认消息出现
    got = False
    for i in range(40):
        try:
            t = page.evaluate("()=>document.body.innerText")
            if "确认后我再开始生成" in t or "视频生成参数确认" in t or "参数确认" in t:
                print(f"[{i*3}s] 检测到确认消息")
                got = True
                break
        except Exception: pass
        time.sleep(3)
    if got:
        # dump 确认消息附近的可点击元素 / 按钮
        info = page.evaluate("""()=>{
            const res=[];
            document.querySelectorAll('button,[role=button],div[class*="confirm"],div[class*="Confirm"]').forEach(e=>{
                const t=(e.textContent||'').trim();
                const r=e.getBoundingClientRect();
                if(!r.width||!r.height)return;
                if(/确认|开始生成|生成|立即|继续|发送|OK|ok/i.test(t) && t.length<30){
                    res.push({tag:e.tagName, text:t.slice(0,30), cls:(e.className||'').toString().slice(0,60), rect:[Math.round(r.x),Math.round(r.y),Math.round(r.width),Math.round(r.height)]});
                }
            });
            return res.slice(0,40);
        }""")
        print("=== 确认相关元素 ===")
        for x in info:
            print(x)
        page.screenshot(path="/tmp/confirm_ui.png")
        print("截图已存 /tmp/confirm_ui.png")
        # 也 dump 输入框状态
        edinfo = page.evaluate("""()=>{const ed=document.querySelector('[contenteditable=true]');return ed?{text:ed.innerText.slice(0,50),placeholder:ed.getAttribute('data-placeholder')||ed.getAttribute('placeholder')||''}:'none';}""")
        print("输入框:", edinfo)
    else:
        print("未检测到确认消息")
    input("探查完毕，按回车退出…")
