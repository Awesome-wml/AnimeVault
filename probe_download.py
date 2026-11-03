#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""探查豆包网页版视频生成后的下载机制：发分镜2 → 等生成 → 观察DOM → 尝试下载"""
import sys, os, json, time
from playwright.sync_api import sync_playwright

PROJECT = "/Users/dongxiangyu/PycharmProjects/dongai"
STATIC  = os.path.join(PROJECT, "static/images")
VOICE_ROOT = "/Users/dongxiangyu/Desktop/ai漫剧/9.22/800+克隆必备音色素材合集/不同年龄人群音色"
PROFILE_DIR = "/Users/dongxiangyu/Library/Application Support/Google/Chrome/Default"
PROMPT_FILE = os.path.join(PROJECT, "shot_prompts.json")

IMG = {
    "萧家演武场": os.path.join(STATIC, "6b0760c8-40b1-4fd0-893a-3058cfc6d289.png"),
    "萧尘":        os.path.join(STATIC, "08b6e945-0dcd-40f6-9ef0-edb3afcfd056.jpg"),
    "赵虎":        os.path.join(STATIC, "64acc4e7-f679-45be-8078-31a0997c81eb.png"),
    "萧天":        os.path.join(STATIC, "a2cb1bd3-68cd-49bb-8f45-512911dce5ec.png"),
    "萧云":        os.path.join(STATIC, "981f307a-c8b7-4c2e-bffe-57e97c59c53f.png"),
    "龙血玉佩":    os.path.join(STATIC, "0782e2a8-ddcb-4572-86c7-c82860a8e1eb.png"),
}
VOICE = {
    "萧尘": os.path.join(VOICE_ROOT, "孩童/男-十二到十四岁的男孩.wav"),
    "赵虎": os.path.join(VOICE_ROOT, "老年/男-傲慢刻薄、凶狠.wav"),
    "萧天": os.path.join(VOICE_ROOT, "老年/男-低音，威严，浓厚.wav"),
    "萧云": os.path.join(VOICE_ROOT, "中年-男声/男-清冷、正派.wav"),
}
SHOT_IMAGES = {
    2:  ["萧家演武场","萧尘","赵虎"],
}
SHOT_VOICES = {
    2:  ["赵虎"],
}

def load_prompts():
    with open(PROMPT_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def send(page, task):
    sn = task["shot"]; assets = task["assets"]; prompt = task["prompt"]
    ed = page.locator("[contenteditable=true]").first
    ed.click(); time.sleep(0.5)
    if assets:
        page.set_input_files("input[type=file]", assets)
        print(f"  已上传 {len(assets)} 个附件")
        for _ in range(20):
            try:
                n = page.evaluate("""()=>{let c=0;document.querySelectorAll('img').forEach(im=>{const s=im.src||'';if(s.includes('byteimg')||s.includes('tos-cn'))c++;});return c;}""")
                if n >= len([a for a in assets if a.lower().endswith(('.png','.jpg','.jpeg','.webp'))]): break
            except Exception: pass
            time.sleep(1)
    try:
        page.evaluate("""(t)=>{const ed=document.querySelector('[contenteditable=true]');ed.focus();document.execCommand('insertText',false,t);}""", prompt)
    except Exception:
        try: ed.fill(prompt)
        except Exception: ed.type(prompt, delay=5)
    time.sleep(1)
    ed.press("Enter"); time.sleep(1)
    try:
        page.eval_on_selector_all("button","els=>{for(const e of els){if((e.textContent||'').trim()==='↑'||e.getAttribute('aria-label')==='发送'){e.click();break;}}}")
    except Exception: pass
    print("  已发送，等待生成视频…")

def probe(page):
    """等视频出现，探查DOM并尝试下载"""
    # 轮询最多 12 分钟，找 video 元素
    t0 = time.time()
    video_found = False
    while time.time() - t0 < 720:
        try:
            info = page.evaluate("""()=>{
                const v=document.querySelectorAll('video');
                const arr=[];
                v.forEach(x=>{arr.push({src:(x.src||'').slice(0,120), poster:(x.poster||'').slice(0,120), w:x.videoWidth, h:x.videoHeight});});
                // 找可能的下载按钮：title/aria 含 下载
                const btns=[];
                document.querySelectorAll('button,[role=button],svg').forEach(e=>{
                    const t=((e.getAttribute&&e.getAttribute('aria-label'))||'') + ((e.getAttribute&&e.getAttribute('title'))||'');
                    if(t.includes('下载')||t.includes('download')) btns.push(t);
                });
                return {videos:arr, downloadBtns:[...new Set(btns)].slice(0,20), videoCount:document.querySelectorAll('video').length};
            }""")
            print(f"[probe t={int(time.time()-t0)}s] videoCount={info['videoCount']} btns={info['downloadBtns']}")
            if info["videoCount"] > 0:
                for v in info["videos"]:
                    print(f"    video src={v['src']} poster={v['poster']} size={v['w']}x{v['h']}")
                video_found = True
                break
        except Exception as e:
            print("probe err", e)
        time.sleep(5)
    if not video_found:
        print("未等到视频出现（12分钟超时）")
        return
    # 尝试下载：优先找下载按钮，用 expect_download
    time.sleep(2)
    for sel_js in [
        """(els)=>els.filter(e=>((e.getAttribute&&(e.getAttribute('aria-label')||e.getAttribute('title')||''))||'').includes('下载'))""",
    ]:
        try:
            with page.expect_download(timeout=10000) as dl_info:
                clicked = page.eval_on_selector_all("button,[role=button]", sel_js)
                print("  点击下载按钮：", clicked)
                if not clicked:
                    break
            dl = dl_info.value
            path = "/tmp/probe_download_" + dl.suggested_filename
            dl.save_as(path)
            print(f"  ✅ 下载成功: {path} ({os.path.getsize(path)} bytes)")
            return
        except Exception as e:
            print("  下载按钮方式失败:", str(e)[:120])
    # 兜底：取 video src 用 page.request 下载
    try:
        src = page.evaluate("""()=>{const v=document.querySelector('video');return v?v.src||v.currentSrc:'';}""")
        if src and src.startswith("http"):
            resp = page.request.get(src)
            print("  video src http status:", resp.status)
            if resp.ok:
                path = "/tmp/probe_video.mp4"
                with open(path,"wb") as f: f.write(resp.body())
                print(f"  ✅ 用video src下载成功: {path} ({os.path.getsize(path)} bytes)")
    except Exception as e:
        print("  video src 方式失败:", str(e)[:120])

def main():
    prompts = {d["shot"]: d["video_prompt"] for d in load_prompts()}
    sn = 2
    imgs = [IMG[n] for n in SHOT_IMAGES[sn]]
    vcs  = [VOICE[n] for n in SHOT_VOICES[sn]]
    task = {"shot":sn,"prompt":prompts.get(sn,""),"assets":imgs+vcs}
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(PROFILE_DIR, channel="chrome", headless=False,
            args=["--disable-blink-features=AutomationControlled"])
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.set_default_timeout(15000)
        page.goto("https://www.doubao.com/chat", timeout=30000)
        print("等待登录检测…")
        for _ in range(900):
            if page.get_by_text("登录", exact=True).count() == 0:
                break
            time.sleep(1)
        send(page, task)
        probe(page)
        # 保持打开 30 秒让用户看
        time.sleep(30)
        ctx.close()

if __name__ == "__main__":
    main()
