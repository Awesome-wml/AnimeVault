#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试：让豆包随便生成一个视频 → 抓取视频直链 → 下载并校验文件。

流程（与历史问答记录一致）：
  新建对话 → 切视频模式 → (可选)选 Seedance 2.0 Fast → 发提示词
  → 兜底确认 → 等"视频生成好了" → 抓 MP4 URL → 下载 → 校验 MP4 头

用法：
  .venv/bin/python test_video_url_capture.py                      # 默认 account_3
  .venv/bin/python test_video_url_capture.py --account account_1
  .venv/bin/python test_video_url_capture.py --prompt "..." --keep-open
"""
import os
import sys
import time
import json
import argparse
import random
import logging
from datetime import datetime

from playwright.sync_api import sync_playwright

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("video-url-test")

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(PROJECT_ROOT, "output_videos")

# 视频直链判定：域名白名单 + 路径后缀，避免把弹窗/接口类 URL 误判成视频
VIDEO_HOST_HINTS = ("vdl.doubao.com", "v26-vdl", "v33-vdl")
VIDEO_PATH_SUFFIX = (".mp4", ".mov", ".m4v")

CANDIDATE_PROMPTS = [
    "一只橘猫在午后阳光的木地板上打滚，暖色调，特写镜头，缓慢运镜。",
    "雨后的城市街道，霓虹倒影，镜头缓慢向前推进，电影感冷色调。",
    "海边日落，海浪轻拍礁石，镜头缓慢平移，暖橙色天空。",
]


# ---------------------------------------------------------------- 工具函数
def is_video_url(url: str) -> bool:
    """只认真正的媒体直链：白名单域名，或路径本身以 .mp4 结尾（忽略 query）。"""
    u = url.lower()
    host = u.split("?")[0]
    if "doubao.com" not in host:
        return False
    if any(h in host for h in VIDEO_HOST_HINTS):
        return True
    return host.endswith(VIDEO_PATH_SUFFIX)


def click_first(page, selectors, desc, timeout=6000, required=False):
    """依次尝试多个选择器，命中即点击，返回是否成功。"""
    for sel in selectors:
        try:
            n = page.locator(sel).count()
            if n == 0:
                continue
            page.locator(sel).first.click(timeout=timeout)
            log.info("✓ %s（命中 %s）", desc, sel)
            return True
        except Exception as e:
            log.debug("  %s 失败 %s: %s", desc, sel, str(e)[:80])
    log.warning("✗ %s 未命中任何选择器: %s", desc, selectors)
    if required:
        raise RuntimeError(f"无法完成：{desc}")
    return False


def dump_state(page, tag):
    """把页面可见按钮/元素打到日志，方便失败时定位。"""
    try:
        info = page.evaluate(
            """() => {
                const out = {buttons: [], videoCount: document.querySelectorAll('video').length,
                             sliders: document.querySelectorAll('[role=slider]').length};
                document.querySelectorAll('button,[role=button]').forEach(b => {
                    const t = (b.innerText || b.textContent || '').trim().replace(/\\s+/g,' ');
                    if (t) out.buttons.push(t.slice(0, 30));
                });
                out.buttons = [...new Set(out.buttons)].slice(0, 50);
                return out;
            }"""
        )
        log.info("[%s] video=%d slider=%d", tag, info["videoCount"], info["sliders"])
        log.info("[%s] 可见按钮: %s", tag, " | ".join(info["buttons"]))
    except Exception as e:
        log.debug("dump_state 失败: %s", e)


def text_exists(page, keywords):
    return page.evaluate(
        """(kw) => {
            for (const el of document.querySelectorAll('*')) {
                if (el.children.length === 0 && kw.some(k => (el.textContent || '').includes(k))) {
                    return true;
                }
            }
            return false;
        }""",
        keywords,
    )


# ---------------------------------------------------------------- 核心步骤
def setup_video_mode(page, model=None):
    """进入视频生成模式。失败不致命——豆包有时默认就是可生成视频的对话。"""
    if not click_first(page, ['button:has-text("视频生成")', '[role=button]:has-text("视频生成")'],
                       "进入视频模式"):
        log.warning("未找到「视频生成」按钮，尝试继续（页面可能已是视频模式）")
        return False
    time.sleep(2)

    if model:
        # 模型选择器：先点开带 Seedance 字样的按钮，再选具体档位
        if click_first(page, ['button:has-text("Seedance")', '[role=button]:has-text("Seedance")',
                              'button:has-text("Seedance 2")'], "打开模型选择器"):
            time.sleep(1)
            if not click_first(page, [f'text={model}', f'[role=option]:has-text("{model}")',
                                      f'li:has-text("{model}")'], f"选择模型 {model}"):
                log.warning("模型选择失败，将使用当前默认模型")
            time.sleep(1)
            page.keyboard.press("Escape")
        time.sleep(1)
    return True


def send_prompt(page, prompt):
    """写入提示词并发送；发送后校验消息是否真的进了对话流。"""
    ok = page.evaluate(
        """(text) => {
            const ed = document.querySelector('[contenteditable=true]');
            if (!ed) return false;
            ed.focus();
            document.execCommand('insertText', false, text);
            return true;
        }""",
        prompt,
    )
    if not ok:
        ed = page.locator("[contenteditable=true]").first
        ed.click()
        ed.fill(prompt)
    time.sleep(0.8)
    page.keyboard.press("Enter")
    log.info("提示词已发送，等待豆包响应…")

    # 校验：提示词片段应出现在对话流里；没出现就点发送按钮补一次
    marker = prompt[:10]
    for attempt in range(2):
        for _ in range(4):
            time.sleep(2)
            if marker in page.inner_text("body"):
                log.info("✓ 已确认提示词进入对话流")
                return True
        if attempt == 0:
            log.warning("未看到提示词进入对话流，尝试点击发送按钮")
            page.evaluate(
                """() => {
                    const cands = document.querySelectorAll('button,[role=button]');
                    for (const b of cands) {
                        const t = (b.innerText || '').trim();
                        const al = b.getAttribute('aria-label') || '';
                        if (t === '↑' || t === '发送' || al.includes('发送')) { b.click(); return; }
                    }
                }"""
            )
    log.warning("⚠ 仍未能确认提示词已送达，继续按流程等待")
    return False


def handle_confirm(page, wait=40):
    """豆包可能反问"确认生成"，自动回复确认（历史经验：确认只是对话文字，不是按钮）。"""
    deadline = time.time() + wait
    while time.time() < deadline:
        if text_exists(page, ["确认生成", "是否生成", "开始生成吗", "确认后我再开始", "确认是否生成"]):
            log.info("检测到豆包要求确认，自动回复「确认」")
            page.evaluate(
                """() => {
                    const ed = document.querySelector('[contenteditable=true]');
                    if (ed) { ed.focus(); document.execCommand('insertText', false, '确认'); }
                }"""
            )
            time.sleep(0.5)
            page.keyboard.press("Enter")
            return True
        time.sleep(3)
    return False


def wait_for_ready(page, url_store, timeout=900):
    """等生成完成：以「视频生成好了」为主信号；直链捕获作为辅助（生成 1 分钟后才提前结束）。"""
    start = time.time()
    last_log = 0
    while time.time() - start < timeout:
        el = int(time.time() - start)
        try:
            if text_exists(page, ["视频生成好了"]):
                log.info("✓ 页面提示「你的视频生成好了」，耗时 %ds", el)
                return "ready"
            if text_exists(page, ["免费体验套餐", "不可用于创作", "额度已用完", "升级正式订阅"]):
                log.error("✗ 豆包提示额度/套餐不足，无法生成")
                return "quota"
        except Exception as e:
            log.debug("轮询异常: %s", str(e)[:80])
        if url_store["urls"] and el >= 60:
            log.info("✓ 已捕获视频直链，耗时 %ds（未等到完成文案，按直链判定完成）", el)
            return "url"
        if el - last_log >= 30:
            log.info("  …仍在生成，已等待 %ds", el)
            last_log = el
        time.sleep(5)
    if url_store["urls"]:
        return "url"
    log.error("✗ 等待超时（%ds）", timeout)
    return "timeout"


def open_player_and_read_url(page):
    """视频未自动加载时，点开封面让 <video> 出现，再读 currentSrc。"""
    # 1) 直接读已有 video 元素
    src = page.evaluate(
        """() => {
            for (const v of document.querySelectorAll('video')) {
                const s = v.currentSrc || v.src || '';
                if (s.startsWith('http')) return s;
            }
            return null;
        }"""
    )
    if src:
        return src

    # 2) 点最大的一张图（生成结果封面）
    try:
        box = page.evaluate(
            """() => {
                let best = null;
                document.querySelectorAll('img').forEach(im => {
                    const r = im.getBoundingClientRect();
                    if (r.width > 240 && r.height > 120 && (!best || r.width * r.height > best.area)) {
                        best = {area: r.width * r.height,
                                cx: r.left + r.width / 2, cy: r.top + r.height / 2};
                    }
                });
                return best;
            }"""
        )
        if box:
            log.info("点击生成结果封面 (%.0f, %.0f)", box["cx"], box["cy"])
            page.mouse.click(box["cx"], box["cy"])
            time.sleep(4)
    except Exception as e:
        log.warning("点击封面失败: %s", str(e)[:100])

    for _ in range(15):
        src = page.evaluate(
            """() => {
                for (const v of document.querySelectorAll('video')) {
                    const s = v.currentSrc || v.src || '';
                    if (s.startsWith('http')) return s;
                }
                return null;
            }"""
        )
        if src:
            return src
        time.sleep(2)
    return None


def download(ctx, page, url, out_path, attempt=1):
    """用带登录 Cookie 的上下文请求直链下载，并校验 MP4 文件头。"""
    log.info("下载中（第 %d 次）：%s", attempt, url[:100] + ("…" if len(url) > 100 else ""))
    data = None

    # A. 上下文请求（带 Cookie / Referer）
    try:
        resp = ctx.request.get(url, headers={"Referer": "https://www.doubao.com/"}, timeout=180000)
        if resp.ok:
            data = resp.body()
            log.info("  A. 上下文下载成功，HTTP %d，%.2f MB", resp.status, len(data) / 1048576)
        else:
            log.warning("  A. 上下文下载 HTTP %d", resp.status)
    except Exception as e:
        log.warning("  A. 上下文下载失败: %s", str(e)[:120])

    # B. 页面内 fetch（能带页面自身的鉴权/签名）
    if not data or len(data) < 10240:
        try:
            arr = page.evaluate(
                """async (u) => {
                    const r = await fetch(u);
                    if (!r.ok) return {err: r.status};
                    const b = await r.arrayBuffer();
                    const bytes = new Uint8Array(b);
                    let s = '';
                    for (let i = 0; i < bytes.length; i += 8192) {
                        s += String.fromCharCode.apply(null, bytes.subarray(i, Math.min(i + 8192, bytes.length)));
                    }
                    return {b64: btoa(s)};
                }""",
                url,
            )
            if arr and arr.get("b64"):
                import base64
                data = base64.b64decode(arr["b64"])
                log.info("  B. 页面 fetch 下载成功，%.2f MB", len(data) / 1048576)
            elif arr:
                log.warning("  B. 页面 fetch 失败，HTTP %s", arr.get("err"))
        except Exception as e:
            log.warning("  B. 页面 fetch 失败: %s", str(e)[:120])

    # C. urllib 兜底（无 Cookie 通常也能下签名直链）
    if not data or len(data) < 10240:
        try:
            import urllib.request
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=180) as r:
                data = r.read()
            log.info("  C. urllib 下载成功，%.2f MB", len(data) / 1048576)
        except Exception as e:
            log.warning("  C. urllib 下载失败: %s", str(e)[:120])

    if not data or len(data) < 10240:
        log.error("三种下载方式均失败")
        return None

    with open(out_path, "wb") as f:
        f.write(data)

    # 校验：MP4 的 ftyp/moov
    head = data[:16]
    is_mp4 = (data[4:8] == b"ftyp") or (b"moov" in data[:65536]) or (b"ftyp" in data[:65536])
    log.info("文件已写入：%s", out_path)
    log.info("文件大小：%.2f MB，头部字节：%s，MP4 校验：%s",
             len(data) / 1048576, head[:12], "通过" if is_mp4 else "未通过（可能是 HTML/错误页）")
    return {"path": out_path, "size": len(data), "is_mp4": bool(is_mp4)}


def read_video_src(page):
    """读取页面里已加载视频的 currentSrc。"""
    try:
        return page.evaluate(
            """() => {
                for (const v of document.querySelectorAll('video')) {
                    const s = v.currentSrc || v.src || '';
                    if (s.startsWith('http')) return s;
                }
                return null;
            }"""
        )
    except Exception:
        return None


def open_existing_conversation(page, conv_id):
    """打开一条已出片的对话，滚动加载历史消息。"""
    url = f"https://www.doubao.com/chat/{conv_id}"
    log.info("打开已有对话：%s", url)
    page.goto(url, timeout=40000)
    time.sleep(8)
    for _ in range(8):
        page.mouse.wheel(0, 1400)
        time.sleep(1.2)
    time.sleep(3)
    try:
        log.info("页面标题：%s", page.title())
    except Exception:
        pass


def capture_from_existing(page, url_store, press_play=True):
    """在已生成视频的对话里抓直链：先看网络监听结果，再读 video，再点封面图。"""
    time.sleep(3)
    if url_store["urls"]:
        return url_store["urls"][0]

    src = read_video_src(page)
    if src:
        log.info("✓ 页面已加载 <video>，直接读取 currentSrc")
        return src

    if not press_play:
        return None

    # 收集可能是视频封面的候选图（面积从大到小）
    cands = page.evaluate(
        """() => {
            const out = [];
            document.querySelectorAll('img').forEach(im => {
                const r = im.getBoundingClientRect();
                if (r.width > 220 && r.height > 120) {
                    out.push({cx: r.left + r.width / 2, cy: r.top + r.height / 2,
                              w: Math.round(r.width), h: Math.round(r.height),
                              src: (im.src || '').slice(0, 60),
                              area: r.width * r.height});
                }
            });
            out.sort((a, b) => b.area - a.area);
            return out.slice(0, 6);
        }"""
    )
    log.info("候选封面图 %d 张：%s", len(cands),
             [(c["w"], c["h"]) for c in cands])

    for i, c in enumerate(cands):
        try:
            page.mouse.click(c["cx"], c["cy"])
            log.info("  点击候选图 #%d (%dx%d)…", i + 1, c["w"], c["h"])
            time.sleep(4)
            if url_store["urls"]:
                return url_store["urls"][0]
            src = read_video_src(page)
            if src:
                log.info("✓ 播放器打开，读到 currentSrc")
                return src
            page.keyboard.press("Escape")
            time.sleep(1)
        except Exception as e:
            log.debug("  点击候选图失败: %s", str(e)[:80])
    return None


def try_download_button(page, out_path):
    """兜底：点击页面上的「下载」按钮，走浏览器原生下载。"""
    try:
        with page.expect_download(timeout=20000) as dl_info:
            clicked = page.evaluate(
                """() => {
                    const cands = document.querySelectorAll('button,[role=button],a');
                    for (const b of cands) {
                        const t = ((b.getAttribute('aria-label') || '') + (b.getAttribute('title') || '')
                                   + (b.innerText || '')).trim();
                        if (t.includes('下载') || t.toLowerCase().includes('download')) {
                            b.click();
                            return true;
                        }
                    }
                    return false;
                }"""
            )
            if not clicked:
                log.warning("  页面上没有「下载」按钮")
        dl = dl_info.value
        dl.save_as(out_path)
        size = os.path.getsize(out_path)
        log.info("✓ 浏览器原生下载成功：%s（%.2f MB）", out_path, size / 1048576)
        with open(out_path, "rb") as f:
            head = f.read(65536)
        return {"path": out_path, "size": size,
                "is_mp4": (head[4:8] == b"ftyp") or (b"ftyp" in head) or (b"moov" in head)}
    except Exception as e:
        log.warning("  下载按钮方式失败: %s", str(e)[:120])
        return None


# ---------------------------------------------------------------- 主流程
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--account", default="account_3", help=".doubao_profiles 下的账号目录")
    ap.add_argument("--prompt", default=None, help="自定义提示词（默认随机选一条简单提示词）")
    ap.add_argument("--model", default="Seedance 2.0 Fast", help="模型，传 none 则不改动")
    ap.add_argument("--timeout", type=int, default=900, help="等待生成超时（秒）")
    ap.add_argument("--keep-open", action="store_true", help="结束后保留浏览器窗口")
    ap.add_argument("--conversation", default=None,
                    help="复用已有对话 ID：不生成新视频，直接抓取该对话里已出片的视频并下载")
    args = ap.parse_args()

    prompt = args.prompt or random.choice(CANDIDATE_PROMPTS)
    prompt = prompt.rstrip() + " 不要确认，不要反问，直接生成视频。"
    profile_dir = os.path.join(PROJECT_ROOT, ".doubao_profiles", args.account)
    os.makedirs(OUT_DIR, exist_ok=True)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = os.path.join(OUT_DIR, f"test_{stamp}.mp4")

    result = {
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "account": args.account,
        "prompt": prompt,
        "url": None,
        "captured_urls": [],
        "download": None,
        "status": "unknown",
    }

    log.info("账号 profile：%s", profile_dir)
    log.info("测试提示词：%s", prompt)

    url_store = {"urls": []}

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            profile_dir,
            channel="chrome",
            headless=False,
            args=["--disable-blink-features=AutomationControlled", "--disable-dev-shm-usage"],
            viewport={"width": 1360, "height": 860},
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.set_default_timeout(30000)

        # 全程监听视频直链（必须在发送前挂上）
        def on_response(resp):
            u = resp.url
            if is_video_url(u) and u not in url_store["urls"]:
                if resp.status in (200, 206):
                    url_store["urls"].append(u)
                    log.info("★ 捕获视频直链（HTTP %d）：%s", resp.status, u[:110] + "…")

        ctx.on("response", on_response)

        try:
            page.goto("https://www.doubao.com/chat/", timeout=40000)
            time.sleep(5)

            if page.query_selector('button:has-text("登录")') is not None:
                raise RuntimeError("该账号未登录豆包，请先手动登录后重试")

            log.info("登录状态：已登录")

            if args.conversation:
                # ---- 复用模式：不生成，直接抓已有视频 ----
                result["mode"] = "reuse"
                result["conversation_id"] = args.conversation
                open_existing_conversation(page, args.conversation)
                dump_state(page, "已有对话")

                url = capture_from_existing(page, url_store)
                if url:
                    result["url"] = url
                    result["captured_urls"] = list(url_store["urls"])
                    log.info("最终使用的直链：%s", url[:140])
                    dl = download(ctx, page, url, out_path)
                else:
                    log.warning("未抓到直链，改用「下载」按钮兜底")
                    dl = try_download_button(page, out_path)
                result["download"] = dl

                if dl and dl["is_mp4"]:
                    result["status"] = "success"
                else:
                    result["status"] = "url_not_found"
                    page.screenshot(path=os.path.join(OUT_DIR, f"fail_{stamp}.png"))
                return

            dump_state(page, "初始页面")
            setup_video_mode(page, None if args.model.lower() == "none" else args.model)
            dump_state(page, "视频模式")

            send_prompt(page, prompt)
            handle_confirm(page, wait=40)

            state = wait_for_ready(page, url_store, timeout=args.timeout)
            result["state"] = state

            if state == "quota":
                result["status"] = "quota_blocked"
                page.screenshot(path=os.path.join(OUT_DIR, f"fail_{stamp}.png"))
                return

            if state == "timeout":
                result["status"] = "timeout"
                page.screenshot(path=os.path.join(OUT_DIR, f"fail_{stamp}.png"))
                return

            # 拿直链：优先网络监听结果，其次读 <video currentSrc>
            url = url_store["urls"][0] if url_store["urls"] else None
            if not url:
                log.info("未从网络监听拿到直链，尝试打开播放器读取 currentSrc…")
                url = open_player_and_read_url(page)
            if not url:
                result["status"] = "url_not_found"
                page.screenshot(path=os.path.join(OUT_DIR, f"fail_{stamp}.png"))
                log.error("✗ 未能获取视频直链")
                return

            result["url"] = url
            result["captured_urls"] = list(url_store["urls"])
            log.info("最终使用的直链：%s", url[:140])

            dl = download(ctx, page, url, out_path)
            result["download"] = dl

            if dl and dl["is_mp4"]:
                result["status"] = "success"
                # 抽一帧缩略图，确认视频真能解码
                try:
                    import subprocess
                    thumb = out_path.replace(".mp4", "_thumb.jpg")
                    subprocess.run(
                        ["ffmpeg", "-y", "-i", out_path, "-frames:v", "1", thumb],
                        capture_output=True, timeout=60,
                    )
                    if os.path.exists(thumb):
                        result["thumb"] = thumb
                        log.info("缩略图：%s", thumb)
                except Exception as e:
                    log.debug("抽帧失败: %s", str(e)[:80])
            else:
                result["status"] = "download_invalid"
                page.screenshot(path=os.path.join(OUT_DIR, f"fail_{stamp}.png"))

        except Exception as e:
            result["status"] = "error"
            result["error"] = str(e)[:300]
            log.error("✗ 流程异常：%s", str(e)[:200])
            try:
                page.screenshot(path=os.path.join(OUT_DIR, f"fail_{stamp}.png"))
            except Exception:
                pass
        finally:
            result["finished_at"] = datetime.now().isoformat(timespec="seconds")
            log_path = os.path.join(OUT_DIR, f"test_{stamp}.json")
            with open(log_path, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            log.info("测试结果：%s", result.get("status"))
            log.info("结果日志：%s", log_path)

            if args.keep_open:
                log.info("--keep-open：60 秒后关闭浏览器")
                time.sleep(60)
            ctx.close()

    if result.get("status") == "success":
        print(f"\n✅ 测试通过：{result['download']['path']} "
              f"({result['download']['size']/1048576:.2f} MB)\n{result['url']}")
    else:
        print(f"\n❌ 测试未通过：status={result.get('status')}  详见 {OUT_DIR}")
        sys.exit(1)


if __name__ == "__main__":
    main()
