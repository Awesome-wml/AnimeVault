#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""完整链路验证：视频生成模式+选Seedance 2.0 Fast/15s/16:9 → 上传分镜1 → 发送 → 等生成 → 下载"""
import os, json, time
from playwright.sync_api import sync_playwright

PROJECT = "/Users/dongxiangyu/PycharmProjects/dongai"
STATIC  = os.path.join(PROJECT, "static/images")
VOICE_ROOT = "/Users/dongxiangyu/Desktop/ai漫剧/9.22/800+克隆必备音色素材合集/不同年龄人群音色"
PROFILE_DIR = "/Users/dongxiangyu/Library/Application Support/Google/Chrome/Default"
PROMPT_FILE = os.path.join(PROJECT, "shot_prompts.json")
OUT_DIR = os.path.join(PROJECT, "output_videos")
os.makedirs(OUT_DIR, exist_ok=True)

VG_BTN = (489, 669)
MODEL_BTN = (571, 670)
DUR_BTN = (785, 670)

IMG = {
    "萧家演武场": os.path.join(STATIC, "6b0760c8-40b1-4fd0-893a-3058cfc6d289.png"),
    "萧尘":        os.path.join(STATIC, "08b6e945-0dcd-40f6-9ef0-edb3afcfd056.jpg"),
    "赵虎":        os.path.join(STATIC, "64acc4e7-f679-45be-8078-31a0997c81eb.png"),
}
VOICE = {
    "萧尘": os.path.join(VOICE_ROOT, "孩童/男-十二到十四岁的男孩.wav"),
    "赵虎": os.path.join(VOICE_ROOT, "老年/男-傲慢刻薄、凶狠.wav"),
}

def load_prompts():
    with open(PROMPT_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def dom_click(page, match, bottom_only=False):
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
        if(hit){ hit.click(); return 'clicked:['+match+']'; }
        return 'notfound:'+match;
    }""", {"match":match,"bottom":bottom_only})

def setup_video_mode(page):
    """进入视频生成模式 + 选 Seedance 2.0 Fast / 15s / 16:9"""
    print("1. 点视频生成:", VG_BTN); page.mouse.click(*VG_BTN); time.sleep(5)
    print("2. 点模型选择器:", MODEL_BTN); page.mouse.click(*MODEL_BTN); time.sleep(3)
    print("  选模型:", dom_click(page, "Seedance 2.0 Fast")); time.sleep(2)
    page.keyboard.press("Escape"); time.sleep(1)   # 关闭模型浮层
    print("3. 点时长:", DUR_BTN); page.mouse.click(*DUR_BTN); time.sleep(3)
    print("  选时长15s:", dom_click(page, "15s")); time.sleep(2)
    page.keyboard.press("Escape"); time.sleep(1)   # 关闭时长浮层
    print("  选比例16:9:", dom_click(page, "16:9")); time.sleep(2)
    page.keyboard.press("Escape"); time.sleep(1)   # 关闭比例浮层
    time.sleep(1)

def send_shot(page, task):
    ed = page.locator("[contenteditable=true]").first
    ed.click(); time.sleep(0.5)
    if task["assets"]:
        page.set_input_files("input[type=file]", task["assets"])
        print(f"  已上传 {len(task['assets'])} 附件")
        for _ in range(20):
            try:
                n = page.evaluate("""()=>{let c=0;document.querySelectorAll('img').forEach(im=>{const s=im.src||'';if(s.includes('byteimg')||s.includes('tos-cn'))c++;});return c;}""")
                if n >= len([a for a in task['assets'] if a.lower().endswith(('.png','.jpg','.jpeg','.webp'))]): break
            except Exception: pass
            time.sleep(1)
    try:
        page.evaluate("""(t)=>{const ed=document.querySelector('[contenteditable=true]');ed.focus();document.execCommand('insertText',false,t);}""", task["prompt"])
    except Exception:
        try: ed.fill(task["prompt"])
        except Exception: ed.type(task["prompt"], delay=5)
    time.sleep(1)
    ed.press("Enter"); time.sleep(1)
    try:
        page.eval_on_selector_all("button","els=>{for(const e of els){if((e.textContent||'').trim()==='↑'||e.getAttribute('aria-label')==='发送'){e.click();break;}}}")
    except Exception: pass
    print("  已发送。")

def wait_and_download(page, shot):
    """等视频出现，探查并下载"""
    t0 = time.time()
    while time.time() - t0 < 720:
        try:
            cnt = page.evaluate("""()=>{return document.querySelectorAll('video').length}""")
            if cnt > 0:
                src = page.evaluate("""()=>{const v=document.querySelector('video');return v?(v.src||v.currentSrc||''):''}""")
                print(f"  视频出现 videoCount={cnt} src={src[:120]}")
                break
        except Exception: pass
        if int(time.time()-t0) % 30 == 0:
            print(f"  [等待生成 {int(time.time()-t0)}s] videoCount=", page.evaluate("""()=>document.querySelectorAll('video').length"""))
        time.sleep(5)
    if not page.evaluate("""()=>document.querySelectorAll('video').length"""):
        print("  未等到视频(12min超时)"); return False
    time.sleep(2)
    # 方式1: 找下载按钮
    try:
        with page.expect_download(timeout=8000) as dl_info:
            page.evaluate("""()=>{const btns=[...document.querySelectorAll('button,[role=button]')];const b=btns.find(e=>((e.getAttribute('aria-label')||e.getAttribute('title')||'')||'').includes('下载'));if(b)b.click();}""")
        dl = dl_info.value
        path = os.path.join(OUT_DIR, f"shot{shot}.mp4")
        dl.save_as(path)
        print(f"  ✅ 下载按钮方式成功: {path} ({os.path.getsize(path)}B)"); return True
    except Exception as e:
        print("  下载按钮方式失败:", str(e)[:100])
    # 方式2: video src 用 page.request 下载
    try:
        src = page.evaluate("""()=>{const v=document.querySelector('video');return v?(v.src||v.currentSrc||''):''}""")
        if src.startswith("http"):
            resp = page.request.get(src)
            print("  video src status:", resp.status, "ctype:", resp.headers.get("content-type"))
            if resp.ok:
                path = os.path.join(OUT_DIR, f"shot{shot}.mp4")
                with open(path,"wb") as f: f.write(resp.body())
                print(f"  ✅ video src下载成功: {path} ({os.path.getsize(path)}B)"); return True
    except Exception as e:
        print("  video src下载失败:", str(e)[:100])
    # 方式3: 打印视频容器HTML找线索
    try:
        html = page.evaluate("""()=>{const v=document.querySelector('video');let p=v;const out=[];for(let i=0;i<6&&p;i++){out.push(p.tagName+':'+(p.className||'').slice(0,60));p=p.parentElement;}return out;}""")
        print("  视频容器链:", html)
    except Exception: pass
    return False

def main():
    prompts = {d["shot"]: d["video_prompt"] for d in load_prompts()}
    sn = 1
    task = {"shot":sn,"prompt":prompts.get(sn,""),"assets":[IMG["萧家演武场"],IMG["萧尘"],IMG["赵虎"]]}
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
        setup_video_mode(page)
        send_shot(page, task)
        ok = wait_and_download(page, sn)
        print("\n下载结果:", ok)
        # 保持打开60秒供查看
        time.sleep(60)
        ctx.close()

if __name__ == "__main__":
    main()
