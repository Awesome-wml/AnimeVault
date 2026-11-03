#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""只读探查豆包"视频生成参数确认"消息内部的确认交互(按钮/快捷回复)。不发送任何内容，不扣额度。"""
import os, time
from playwright.sync_api import sync_playwright

PROFILE_DIR = "/Users/dongxiangyu/Library/Application Support/Google/Chrome/Default"

with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(
        PROFILE_DIR, channel="chrome", headless=False,
        viewport={"width":1280,"height":720}, args=["--disable-blink-features=AutomationControlled"],
    )
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.goto("https://www.doubao.com/chat/38451289936088322", wait_until="domcontentloaded")
    time.sleep(5)
    print("=== 定位确认消息并dump其HTML ===")
    html = page.evaluate("""()=>{
        // 找含"确认后我再开始生成视频"的文本节点，向上找消息容器
        let el=null;
        const walker=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);
        while(walker.nextNode()){
            const n=walker.currentNode;
            if(n.textContent && n.textContent.includes('确认后我再开始生成视频')){ el=n.parentElement; break; }
        }
        if(!el) return 'NOT_FOUND_CONFIRM_TEXT';
        // 向上3层取容器
        let cont=el;
        for(let i=0;i<4 && cont.parentElement;i++) cont=cont.parentElement;
        return {
            confirmText: (cont.innerText||'').slice(0,300),
            buttons: [...cont.querySelectorAll('button,[role=button],a,[data-testid],[class*=btn]')].map(b=>{
                const r=b.getBoundingClientRect();
                return {tag:b.tagName, text:(b.textContent||'').trim().slice(0,40), cls:(b.className||'').toString().slice(0,80),
                        rect:[Math.round(r.x),Math.round(r.y),Math.round(r.width),Math.round(r.height)]};
            }).filter(x=>x.text||x.cls),
            html: cont.outerHTML.slice(0,2500)
        };
    }""")
    import json
    print(json.dumps(html, ensure_ascii=False, indent=1)[:3500])
    page.screenshot(path="/tmp/confirm_msg.png")
    print("截图: /tmp/confirm_msg.png")
    time.sleep(2)
    ctx.close()
