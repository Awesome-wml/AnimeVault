"""
豆包视频生成自动化
流程：新对话 → 切视频模式 → 选Seedance 2.0 Fast → 传图 → 发提示词 → 等生成 → 下载视频

关键修复（2026-11-04）：
- 新建对话改为点「新对话」按钮，而不是刷新首页
- 视频直链监听挂在 context 上，发送前就开始抓
- 确认兜底改为轮询 60s，而不是只看一次
- 下载改用带登录 Cookie/Referer 的 context.request，兜底页面 fetch
- URL 过滤收紧为 vdl.doubao.com 白名单，避免误判接口 URL
- 识别额度耗尽，不再干等超时
"""
import os
import time
import base64
import logging
from pathlib import Path
from typing import List, Dict, Optional
from playwright.sync_api import sync_playwright, Page, BrowserContext

from core.providers import fake
from core.doubao_quota import DEFAULT_COST_KEY, QuotaWatcher, cost_between, fake_quota
from utils.file_util import FileUtil

logger = logging.getLogger(__name__)

# 豆包视频直链的固定 host 特征（v26-vdl.doubao.com / v33-vdl.doubao.com 都含 vdl.doubao.com）
VIDEO_HOST_MARK = "vdl.doubao.com"
# 额度耗尽时豆包的回复特征
QUOTA_HINTS = ("免费体验套餐", "不可用于创作", "额度已用完", "升级正式订阅", "今日额度")


def _is_video_url(url: str) -> bool:
    u = (url or "").lower()
    return VIDEO_HOST_MARK in u


def _to_clean_url(url: str) -> str:
    """把水印直链替换成无水印版本。"""
    return url.replace("lr=video_gen_watermark_dyn", "lr=unwatermarked")


class DoubaoVideoGenerator:
    """豆包视频生成器"""

    def __init__(self, project_root: str, status_callback=None):
        self.project_root = Path(project_root)
        # 与图片/音频共用 settings.STATIC_DIR（返回的 videos/xxx 由 /static 挂载对外提供）
        self.static_dir = FileUtil.get_static_dir()
        self.videos_dir = self.static_dir / "videos"
        self.videos_dir.mkdir(parents=True, exist_ok=True)
        self.images_dir = FileUtil.get_images_dir()
        # 本次会话抓到的所有视频直链
        self.video_urls: List[str] = []
        self._pw = None
        self.context: Optional[BrowserContext] = None
        self.status_callback = status_callback  # 状态推送回调
        self.last_cookies: list = []  # 任务结束后回写用的最新 cookie
        # 会员额度：监听挂在 context 上，页面每次打开 /chat/ 都顺带拿到最新读数
        self.quota = QuotaWatcher()
        self.last_quota: Optional[dict] = None   # 最近一次额度读数（规范化），由调用方写回账号
        self.cost_samples: list = []             # 本次成功生成的单条消耗 [(成本分键, used 差值)]

    def _push_status(self, shot_no: int, step: str, progress: int = 0, msg: str = ""):
        """推送当前生成状态"""
        if self.status_callback:
            try:
                self.status_callback({
                    "shot_no": shot_no,
                    "step": step,
                    "progress": progress,
                    "msg": msg
                })
            except Exception:
                pass

    # ------------------------------------------------------------------ 连接
    def _attach_response_listener(self, context: BrowserContext):
        def _on_response(resp):
            try:
                u = resp.url
                if _is_video_url(u) and resp.status in (200, 206):
                    if u not in self.video_urls:
                        self.video_urls.append(u)
                        logger.info("抓到视频直链: %s...", u[:120])
                        import json
                        with open(self.project_root / "output_videos" / "_captured_urls.json", "a") as f:
                            f.write(json.dumps({"ts": time.time(), "url": u}) + "\n")
            except Exception:
                pass
        context.on("response", _on_response)
        self.quota.attach(context)

    def connect_with_cookies(self, cookies: list, headless: bool = False) -> tuple:
        """用数据库里存的 cookie 建立无目录 context（不落地 Profile）。"""
        self._pw = sync_playwright().start()
        try:
            browser = self._pw.chromium.launch(
                channel="chrome",
                headless=headless,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                ],
            )
            context = browser.new_context(
                viewport={"width": 1280, "height": 800},
            )
            if cookies:
                context.add_cookies(cookies)
            self.context = context
            self._attach_response_listener(context)

            page = context.pages[0] if context.pages else context.new_page()
            page.set_default_timeout(30000)
            return self._pw, context, page
        except Exception as e:
            if self._pw:
                self._pw.stop()
            raise e

    def connect_to_profile(self, profile_dir: str, headless: bool = False) -> tuple:
        """持久化目录连接，仅用于首次扫码登录 / 检查登录态。"""
        profile_path = self.project_root / profile_dir
        profile_path.mkdir(parents=True, exist_ok=True)

        self._pw = sync_playwright().start()
        try:
            context = self._pw.chromium.launch_persistent_context(
                str(profile_path),
                channel="chrome",
                headless=headless,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                ],
                viewport={"width": 1280, "height": 800},
            )
            self.context = context
            self._attach_response_listener(context)

            page = context.pages[0] if context.pages else context.new_page()
            page.set_default_timeout(30000)
            return self._pw, context, page
        except Exception as e:
            if self._pw:
                self._pw.stop()
            raise e

    @staticmethod
    def export_cookies(context: BrowserContext) -> list:
        """导出当前 context 的 cookie 列表（明文 JSON 可入库）。"""
        try:
            return context.cookies()
        except Exception:
            return []

    def _connect(self, profile_dir: str = "", cookies: list = None,
                 headless: bool = False) -> tuple:
        """优先用数据库 cookie 建立无目录 context；无 cookie 时回退到 Profile 目录。"""
        if cookies:
            return self.connect_with_cookies(cookies, headless=headless)
        return self.connect_to_profile(profile_dir, headless=headless)

    def check_login_status(self, page: Page) -> bool:
        try:
            page.goto("https://www.doubao.com/chat", timeout=30000)
            self._wait_js(page,
                "() => !!document.querySelector('[contenteditable=true]')", 10000)
            login_btn = page.query_selector('button:has-text("登录")')
            return login_btn is None
        except Exception as e:
            logger.error(f"检查登录状态失败: {e}")
            return False

    def _wait_js(self, page: Page, js_expr: str, timeout: int = 8000,
                 interval: float = 0.3) -> bool:
        """轮询直到页面上的 JS 表达式返回真值，替代固定 sleep。"""
        end = time.time() + timeout / 1000
        while time.time() < end:
            try:
                if page.evaluate(js_expr):
                    return True
            except Exception:
                pass
            time.sleep(interval)
        return False

    # ------------------------------------------------------------------ UI 操作
    def new_conversation(self, page: Page):
        """真正新建对话：点侧栏「新对话」。页面已在 chat 页，不重复 goto。"""
        self._wait_js(page,
            """() => [...document.querySelectorAll('*')].some(el => {
                const t = (el.innerText || '').trim();
                return t.startsWith('新对话') && el.getBoundingClientRect().left < 240;
            })""", 8000)
        try:
            page.click('button:has-text("新对话")', timeout=3000)
            logger.info("已新建对话(按钮)")
        except Exception:
            pos = page.evaluate(
                """() => {
                    for (const el of document.querySelectorAll('*')) {
                        if ((el.innerText || '').trim().startsWith('新对话') &&
                            el.getBoundingClientRect().left < 240 &&
                            el.getBoundingClientRect().width > 30) {
                            const r = el.getBoundingClientRect();
                            return {cx: r.left + r.width/2, cy: r.top + r.height/2};
                        }
                    }
                    return null;
                }"""
            )
            if pos:
                page.mouse.click(pos["cx"], pos["cy"])
                logger.info("已新建对话(点行)")
            else:
                page.keyboard.press("Meta+Shift+k")
        time.sleep(1.5)
        # 等输入框就绪
        self._wait_js(page,
            "() => !!document.querySelector('[contenteditable=true]')", 8000)

    def switch_to_video_mode(self, page: Page):
        """切换到视频生成模式，选 Seedance 2.0 Fast。"""
        # 0a. 首选：直接点底部输入栏的「视频生成」chip（新版 UI 直接有）
        if self._click_bottom_chip(page, "视频生成"):
            time.sleep(1.5)
        else:
            # 0b. 兜底：输入框打 /视频生成，选候选
            page.evaluate("() => { document.querySelector('[contenteditable=true]').focus(); }")
            page.keyboard.type("/视频生成", delay=80)
            self._wait_js(page,
                """() => [...document.querySelectorAll('*')].some(el => {
                    const t = (el.innerText || '').trim();
                    return t === '视频生成' && el.getBoundingClientRect().left > 200;
                })""", 4000)
            page.keyboard.press("Enter")
            time.sleep(1.5)

        # 等视频模式激活：输入栏出现视频相关 chip
        if not self._wait_js(page,
            """() => [...document.querySelectorAll('*')].some(el => {
                const t = (el.textContent || '').trim();
                const r = el.getBoundingClientRect();
                return (r.bottom > 650 && r.width > 0 && el.children.length <= 1 &&
                        (t.includes('视频') || t.includes('Seedance') || t.includes('创意视频')));
            })""", 6000):
            logger.info("/视频生成未激活，走菜单兜底")
            self._enter_video_via_menu(page)
            self._wait_js(page,
                """() => [...document.querySelectorAll('*')].some(el => {
                    const t = (el.textContent || '').trim();
                    const r = el.getBoundingClientRect();
                    return (r.bottom > 650 && r.width > 0 && el.children.length <= 1 &&
                            (t.includes('视频') || t.includes('Seedance') || t.includes('创意视频')));
                })""", 8000)

        # 选 Seedance 2.0 Fast
        try:
            page.click('button:has-text("Seedance")', timeout=5000)
            self._wait_js(page,
                """() => [...document.querySelectorAll('*')].some(el =>
                   (el.textContent || '').trim() === 'Seedance 2.0 Fast')""", 3000)
            page.click('text=Seedance 2.0 Fast', timeout=5000)
        except Exception:
            logger.warning("未切换模型，沿用当前默认模型")

        # 拖时长滑块到最右（15s）：拖到轨道右端 x=925（1280 视口下）
        try:
            page.click('button:has-text("自动")', timeout=4000)
            self._wait_js(page, "() => !!document.querySelector('[role=slider]')", 4000)
            thumb = page.evaluate(
                """() => {
                    const el = document.querySelector('[role=slider]');
                    if (!el) return null;
                    const r = el.getBoundingClientRect();
                    return {x: r.x + r.width/2, y: r.y + r.height/2};
                }"""
            )
            if thumb:
                page.mouse.move(thumb["x"], thumb["y"])
                page.mouse.down()
                time.sleep(0.2)
                page.mouse.move(925, thumb["y"], steps=25)
                time.sleep(0.4)
                page.mouse.up()
                time.sleep(0.6)
                label = page.evaluate(
                    """() => {
                        for (const b of document.querySelectorAll('button,[role=button]')) {
                            const t = (b.innerText || '').trim();
                            if (/15\\s*s/i.test(t)) return t;
                        }
                        return '';
                    }"""
                )
                logger.info("时长设置结果: %s", label or "未显示15s")
            page.keyboard.press("Escape")
        except Exception:
            logger.warning("时长滑块设置失败，沿用默认时长")

        logger.info("已切换到视频生成模式")

    def _enter_video_via_menu(self, page: Page):
        """菜单兜底：工作 toggle → 技能 → 视频生成/创意视频/Seedance。"""
        if not self._click_bottom_chip(page, "技能"):
            logger.info("对话模式，先切到「工作」")
            self._click_main_toggle(page, "工作")
            self._wait_js(page,
                """() => [...document.querySelectorAll('*')].some(el => {
                    const t = (el.innerText || '').trim();
                    return t === '技能' && el.getBoundingClientRect().bottom > 550;
                })""", 5000)
            self._click_bottom_chip(page, "技能")
        for name in ("视频生成", "创意视频", "Seedance"):
            try:
                page.click(f'text={name}', timeout=3000)
                logger.info("已点技能「%s」", name)
                return
            except Exception:
                continue
        logger.warning("菜单兜底也没找到视频入口")

    def _click_bottom_chip(self, page: Page, label: str) -> bool:
        """点击底部输入栏里文字为 label 的 chip（避开侧边栏同名按钮）。"""
        try:
            pos = page.evaluate(
                """(label) => {
                    let best = null;
                    for (const el of document.querySelectorAll('*')) {
                        const t = (el.innerText || '').trim();
                        if (t !== label) continue;
                        const r = el.getBoundingClientRect();
                        if (r.bottom < 550 || r.width < 10) continue;
                        if (!best || r.width > best.w)
                            best = {cx: r.left + r.width / 2, cy: r.top + r.height / 2, w: r.width};
                    }
                    return best;
                }""",
                label,
            )
            if pos:
                page.mouse.click(pos["cx"], pos["cy"])
                time.sleep(0.6)
                return True
        except Exception as e:
            logger.debug("点底部 chip %s 失败: %s", label, e)
        return False

    def _click_main_toggle(self, page: Page, label: str) -> bool:
        """点主区域中间的切换文字（如 对话/工作 toggle），避开侧边栏和底部。"""
        try:
            pos = page.evaluate(
                """(label) => {
                    for (const el of document.querySelectorAll('*')) {
                        if ((el.innerText || '').trim() !== label) continue;
                        const r = el.getBoundingClientRect();
                        if (r.width < 20 || r.left < 250 || r.top < 250 || r.top > 500) continue;
                        return {cx: r.left + r.width/2, cy: r.top + r.height/2};
                    }
                    return null;
                }""",
                label,
            )
            if pos:
                page.mouse.click(pos["cx"], pos["cy"])
                time.sleep(1.2)
                return True
        except Exception as e:
            logger.debug("点主区域 %s 失败: %s", label, e)
        return False

    def upload_images(self, page: Page, image_paths: list):
        """上传所有参考图片（一次性传完）"""
        valid = [p for p in image_paths if os.path.exists(p)]
        if not valid:
            logger.warning("没有有效的图片可上传")
            return

        file_input = page.query_selector('input[type=file]')
        if file_input:
            file_input.set_input_files(valid)
            # 等上传缩略图出现，最多 12 秒
            self._wait_js(page,
                """() => [...document.querySelectorAll('img')].some(im => {
                    const r = im.getBoundingClientRect();
                    return r.width > 40 && r.bottom > 600;
                })""", 12000)
            logger.info("已上传 %d 张参考图: %s",
                        len(valid), [os.path.basename(p) for p in valid])
        else:
            logger.warning("未找到文件上传 input")

    # ------------------------------------------------------------------ 发送与确认
    def _send_prompt_fast(self, page: Page, prompt: str):
        """只发提示词，不等确认。确认由后续轮询统一处理。"""
        page.evaluate(
            """(text) => {
                const ed = document.querySelector('[contenteditable=true]');
                if (ed) { ed.focus(); document.execCommand('insertText', false, text); }
            }""",
            prompt,
        )
        time.sleep(0.5)
        page.keyboard.press("Enter")
        logger.info("提示词已发送")

    def _handle_confirm_for(self, page: Page) -> bool:
        """检查页面是否要求确认，是则回复。返回是否已确认。"""
        asked = self._page_contains(page, ["确认生成", "是否生成", "开始生成吗", "确认后我再开始", "确认后再开始"])
        if asked:
            logger.info("检测到确认要求，自动回复")
            self._do_confirm(page)
            time.sleep(3)
            return True
        return False

    def send_prompt(self, page: Page, prompt: str):
        """输入提示词并发送，必须等到确认被处理或真正开始渲染才返回。"""
        page.evaluate(
            """(text) => {
                const ed = document.querySelector('[contenteditable=true]');
                if (ed) { ed.focus(); document.execCommand('insertText', false, text); }
            }""",
            prompt,
        )
        time.sleep(0.5)
        page.keyboard.press("Enter")
        logger.info("提示词已发送")

        confirmed = False
        # 最多等 120s：等"确认生成吗"出现并处理，或检测到真正开始渲染
        for i in range(40):
            time.sleep(3)
            # 先看有没有确认按钮/文字
            asked = self._page_contains(page, ["确认生成", "是否生成", "开始生成吗", "确认后我再开始", "确认后再开始"])
            if asked and not confirmed:
                logger.info("检测到豆包要求确认，自动回复")
                self._do_confirm(page)
                confirmed = True
                time.sleep(5)
                continue
            # 确认后或无需确认时，检测渲染开始
            if self._page_contains(page, ["正在渲染", "已启动视频生成", "开始生成视频", "正在生成视频", "预计等待"]):
                logger.info("已开始渲染")
                return
        logger.warning("等待确认/渲染超时 120s")

    def _page_contains(self, page: Page, keywords) -> bool:
        try:
            return page.evaluate(
                """(kws) => {
                    for (const el of document.querySelectorAll('*')) {
                        if (el.children.length !== 0) continue;
                        const t = el.textContent || '';
                        if (kws.some(k => t.includes(k))) return true;
                    }
                    return false;
                }""",
                list(keywords),
            )
        except Exception:
            return False

    def _do_confirm(self, page: Page):
        """优先点页面上的确认按钮/选项，点不到再打字回复。"""
        clicked = False
        try:
            clicked = page.evaluate(
                """() => {
                    const cands = document.querySelectorAll('button,[role=button],[role=option],a');
                    for (const b of cands) {
                        const t = ((b.innerText || '') + (b.getAttribute && (b.getAttribute('aria-label') || ''))).trim();
                        if (t.includes('确认生成') || t.includes('开始生成') || t === '确认' ||
                            t.includes('确认并开始') || t.includes('确认开始')) {
                            b.click();
                            return true;
                        }
                    }
                    return false;
                }"""
            )
        except Exception:
            pass
        if clicked:
            logger.info("已点击确认按钮")
            return
        # 兜底：打字回复
        page.evaluate(
            """() => {
                const ed = document.querySelector('[contenteditable=true]');
                if (ed) { ed.focus(); document.execCommand('insertText', false, '确认，开始生成'); }
            }"""
        )
        page.keyboard.press("Enter")
        logger.info("已打字回复「确认，开始生成」")
        time.sleep(2)

    # ------------------------------------------------------------------ 等待与抓 URL
    def _quota_blocked(self, page: Page) -> bool:
        return page.evaluate(
            """(hints) => {
                for (const el of document.querySelectorAll('*')) {
                    if (el.children.length !== 0) continue;
                    const t = el.textContent || '';
                    if (hints.some(h => t.includes(h))) return true;
                }
                return false;
            }""",
            list(QUOTA_HINTS),
        )

    def wait_for_video(self, page: Page, timeout: int = 1200) -> Optional[str]:
        """等生成完成并返回视频直链。"""
        logger.info("等待视频生成（最多 %d 秒）...", timeout)
        start = time.time()
        confirmed = False

        while time.time() - start < timeout:
            if self.video_urls:
                return self.video_urls[0]
            if self._quota_blocked(page):
                logger.error("账号额度/套餐不足，停止等待")
                return None
            # 流式输出可能在 send_prompt 的 90s 窗口之后才打出确认行，等待期内兜底
            if not confirmed and self._page_contains(page,
                    ["确认后我再开始", "确认后再开始", "确认生成吗", "是否开始生成",
                     "确认后开始生成"]):
                logger.info("等待期间检测到确认要求，自动回复")
                self._do_confirm(page)
                confirmed = True
            try:
                ready = page.evaluate(
                    """() => {
                        for (const el of document.querySelectorAll('*')) {
                            if (el.children.length === 0 &&
                                (el.textContent || '').includes('视频生成好了')) return true;
                        }
                        return false;
                    }"""
                )
                if ready:
                    logger.info("页面提示视频已生成")
                    break
            except Exception:
                pass
            time.sleep(3)
        else:
            logger.warning("等待视频超时")
            return self.video_urls[0] if self.video_urls else None

        time.sleep(3)
        if self.video_urls:
            return self.video_urls[0]

        # 滚到底部，结果封面在最新消息（最下面）
        for _ in range(4):
            try:
                page.mouse.wheel(0, 1500)
            except Exception:
                pass
            time.sleep(0.8)
        time.sleep(2)

        # 等结果封面渲染出来（刚提示"已生成"时封面可能还没挂载）
        boxes = []
        for _ in range(15):
            boxes = self._candidate_covers(page)
            if boxes:
                break
            time.sleep(1)

        # 从最下面的大图往上逐个点；每个点最多重试 3 次（React 刚挂载时点击可能无效）
        for box in boxes:
            for _attempt in range(3):
                try:
                    page.mouse.click(box["cx"], box["cy"])
                except Exception:
                    continue
                time.sleep(3)
                for _ in range(6):
                    if self.video_urls:
                        return self.video_urls[0]
                    src = self._read_video_src(page)
                    if src and "vdl.doubao.com" in src:
                        self.video_urls.append(src)
                        return src
                    time.sleep(2)
            try:
                page.keyboard.press("Escape")
            except Exception:
                pass
            time.sleep(1)

        # 失败留证
        try:
            page.screenshot(path=str(self.project_root / "output_videos" /
                                    f"novideo_{int(time.time())}.png"))
        except Exception:
            pass
        logger.error("点了所有候选封面仍未抓到视频直链")
        return None

    def _candidate_covers(self, page: Page) -> list:
        """候选封面图：宽>240的大图，按位置从下到上排序（最新消息在最下面）。"""
        try:
            boxes = page.evaluate(
                """() => {
                    const out = [];
                    document.querySelectorAll('img').forEach(im => {
                        const r = im.getBoundingClientRect();
                        if (r.width > 240 && r.height > 120) {
                            out.push({cx: r.left + r.width/2, cy: r.top + r.height/2,
                                      area: r.width * r.height});
                        }
                    });
                    out.sort((a, b) => b.cy - a.cy);  // 最下面的先点
                    return out;
                }"""
            )
            return boxes or []
        except Exception:
            return []

    def _read_video_src(self, page: Page) -> Optional[str]:
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

    def _open_result_cover(self, page: Page):
        """兼容旧调用：点最下面的大图。"""
        boxes = self._candidate_covers(page)
        if boxes:
            page.mouse.click(boxes[0]["cx"], boxes[0]["cy"])
            time.sleep(3)

    # ------------------------------------------------------------------ 下载
    def download_video(self, page: Page, video_url: str, shot_no: int) -> str:
        """下载视频到 static/videos/，优先带登录态的 context.request。"""
        filename = f"shot_{shot_no:03d}_{int(time.time())}.mp4"
        save_path = self.videos_dir / filename

        try:
            clean_url = _to_clean_url(video_url)
            if clean_url != video_url:
                logger.info("已转无水印URL: %s", clean_url)
            else:
                logger.warning("URL无水印参数可替换: %s", video_url)
            data = self._fetch_bytes(page, clean_url)
            if not data:
                logger.error("三种下载方式均失败: %s", video_url)
                return ""

            with open(save_path, "wb") as f:
                f.write(data)

            # 校验：MP4 头部
            ok = data[4:8] == b"ftyp" or b"ftyp" in data[:65536]
            logger.info("视频已保存: %s (%.2f MB, MP4校验=%s)",
                        save_path, len(data) / 1048576, ok)
            if not ok:
                logger.warning("下载内容不像 MP4，可能是错误页")
            # 截最后一帧存为参考图
            try:
                import subprocess
                frame_path = self.images_dir / save_path.stem
                frame_path = frame_path.with_suffix(".png")
                subprocess.run(
                    ["ffmpeg", "-y", "-sseof", "-0.5", "-i", str(save_path),
                     "-frames:v", "1", str(frame_path)],
                    capture_output=True, timeout=15
                )
                if frame_path.exists():
                    logger.info("已截尾帧: %s", frame_path.name)
                    return f"videos/{filename}", f"images/{frame_path.name}"
            except Exception as e:
                logger.debug("截尾帧失败: %s", e)
            return f"videos/{filename}", ""
        except Exception as e:
            logger.error("下载视频失败: %s", e)
            return ""

    def _fetch_bytes(self, page: Page, url: str) -> Optional[bytes]:
        """A. context.request(带Cookie) → B. 页面fetch → C. urllib。"""
        # A. 带登录 Cookie 的请求
        try:
            if self.context:
                resp = self.context.request.get(
                    url, headers={"Referer": "https://www.doubao.com/"}, timeout=180000)
                if resp.ok:
                    logger.info("A. context.request 下载成功 %d, %.2f MB",
                                resp.status, len(resp.body()) / 1048576)
                    return resp.body()
        except Exception as e:
            logger.warning("A. context.request 失败: %s", str(e)[:120])

        # B. 页面内 fetch
        try:
            arr = page.evaluate(
                """async (u) => {
                    const r = await fetch(u);
                    if (!r.ok) return {err: r.status};
                    const b = await new Uint8Array(await r.arrayBuffer());
                    let s = '';
                    for (let i = 0; i < b.length; i += 8192)
                        s += String.fromCharCode.apply(null, b.subarray(i, i + 8192));
                    return {b64: btoa(s)};
                }""",
                url,
            )
            if arr and arr.get("b64"):
                return base64.b64decode(arr["b64"])
        except Exception as e:
            logger.warning("B. 页面 fetch 失败: %s", str(e)[:120])

        # C. urllib 兜底
        try:
            import urllib.request
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=180) as r:
                return r.read()
        except Exception as e:
            logger.warning("C. urllib 失败: %s", str(e)[:120])
        return None

    # ------------------------------------------------------------------ 批量
    # ------------------------------------------------------------------ 额度
    def _quota_now(self, page: Page, refresh: bool) -> dict:
        """refresh=False 用页面最近一次自动请求到的读数（刚打开过 /chat/ 时），否则重新打开 /chat/ 读。"""
        if not refresh and self.quota.summary is None and not fake.enabled():
            self.quota.wait_new(page, self.quota.seq, timeout_ms=4000)  # 页面刚打开，额度请求可能还没回来
        q = self.quota.refresh(page) if refresh or self.quota.summary is None else self.quota.snapshot()
        if q.get("ok") or self.last_quota is None:
            self.last_quota = q
        return q

    def _record_cost(self, before: Optional[dict], after: Optional[dict], count: int = 1):
        """成功生成后记录单条消耗 = used 差值 / 条数；差值≤0 或读数无效不记。"""
        diff = cost_between(before, after)
        if diff is not None and count > 0:
            cost = diff / count
            cost = int(cost) if float(cost).is_integer() else round(cost, 2)
            self.cost_samples.append((DEFAULT_COST_KEY, cost))
            logger.info("本次单条消耗额度: %s（%s）", cost, DEFAULT_COST_KEY)

    @staticmethod
    def _member_exhausted(q: Optional[dict]) -> bool:
        return bool(q and q.get("ok") and q.get("is_member") and q.get("exhausted"))

    def generate_batch(self, profile_dir: str = "", tasks: List[Dict] = None,
                       interval: int = 8, send_only: bool = False,
                       cookies: list = None) -> Dict:
        """
        批量生成视频
        每个任务：新对话 → 视频模式 → Fast模型 → 传图 → 发提示词 → 等生成 → 下载
        send_only=True 时：发完提示词就跳下一个，不等出片、不下载。
        """
        tasks = tasks or []
        if fake.enabled():
            return self._fake_generate(tasks)
        result = {"success": [], "failed": [], "total": len(tasks), "videos": {}}

        p, context, page = None, None, None
        try:
            p, context, page = self._connect(profile_dir, cookies)
            if not self.check_login_status(page):
                raise Exception("账号未登录")

            # 每条生成前后各读一次额度：check_login_status 刚打开过 /chat/，第一条的「前」直接用它的读数；
            # 成功后的「后」读数就是下一条的「前」；失败后下一条重新读。
            before, stale = None, False
            for task in tasks:
                shot_no = task.get("shot_no", 0)
                prompt = task.get("prompt", "")
                assets = task.get("assets", [])
                self.video_urls.clear()

                before = self._quota_now(page, refresh=stale or before is not None and not before.get("ok"))
                stale = False
                if self._member_exhausted(before):
                    logger.error("会员额度已用完，批量提前结束")
                    for rest in tasks[tasks.index(task):]:
                        result["failed"].append(rest.get("shot_no", 0))
                        self._push_status(rest.get("shot_no", 0), "failed", 0, "额度已用完")
                    break

                try:
                    logger.info("=== 处理分镜 %s ===", shot_no)
                    self._push_status(shot_no, "connecting", 10, "建立浏览器链接")
                    self.new_conversation(page)
                    self._push_status(shot_no, "new_chat", 20, "新建对话")
                    self.switch_to_video_mode(page)
                    self._push_status(shot_no, "video_mode", 30, "切换到视频生成模式")

                    images = [a for a in assets
                              if a.lower().endswith(('.png', '.jpg', '.jpeg', '.webp'))]
                    if images:
                        self._push_status(shot_no, "upload", 40, "上传参考图")
                        self.upload_images(page, images)

                    self._push_status(shot_no, "send_prompt", 50, "发送提示词")
                    self.send_prompt(page, prompt)

                    self._push_status(shot_no, "generating", 60, "视频生成中...")
                    video_url = self.wait_for_video(page, timeout=1200)
                    if video_url:
                        self._push_status(shot_no, "got_url", 80, "提取视频URL")
                        video_path, _ = self.download_video(page, video_url, shot_no)
                        if video_path:
                            result["success"].append(shot_no)
                            result["videos"][shot_no] = video_path
                            self._push_status(shot_no, "done", 100, "生成完成")
                            logger.info("分镜 %s 完成: %s", shot_no, video_path)
                            after = self._quota_now(page, refresh=True)
                            self._record_cost(before, after)
                            before = after
                        else:
                            result["failed"].append(shot_no)
                            self._push_status(shot_no, "failed", 0, "下载失败")
                            stale = True
                    else:
                        result["failed"].append(shot_no)
                        stale = True
                        # 额度耗尽就整批停止，别再试后面的
                        if self._quota_blocked(page):
                            logger.error("额度耗尽，批量提前结束")
                            self._quota_now(page, refresh=True)
                            break
                except Exception as e:
                    logger.error("分镜 %s 异常: %s", shot_no, e)
                    result["failed"].append(shot_no)
                    stale = True

                time.sleep(interval)

            logger.info("批量完成: 成功%d, 失败%d",
                        len(result["success"]), len(result["failed"]))
        except Exception as e:
            logger.error("批量生成异常: %s", e)
            raise
        finally:
            if context:
                try:
                    self.last_cookies = self.export_cookies(context)
                    context.close()
                except Exception:
                    pass
            if p:
                try:
                    p.stop()
                except Exception:
                    pass
        return result

    def _fake_generate(self, tasks: List[Dict], on_video_ready=None) -> Dict:
        """替身模式：不开浏览器，把固定小视频拷进 static/videos，状态推送与回调照常走。"""
        result = {"success": [], "failed": [], "total": len(tasks), "videos": {}}
        self.last_quota = fake_quota()  # 替身额度固定不变，不产生成本样本
        for task in tasks:
            shot_no = task.get("shot_no", 0)
            self._push_status(shot_no, "generating", 60, "视频生成中...")
            filename = f"shot_{int(shot_no):03d}_{int(time.time() * 1000)}.mp4"
            (self.videos_dir / filename).write_bytes(fake.video_bytes())
            video_path = f"videos/{filename}"
            result["success"].append(shot_no)
            result["videos"][shot_no] = video_path
            if on_video_ready:
                on_video_ready(task.get("shot_id"), shot_no, video_path, "")
            self._push_status(shot_no, "done", 100, "生成完成")
        return result

    def generate_parallel(self, profile_dir: str = "", tasks: List[Dict] = None,
                         max_parallel: int = 5, on_video_ready=None,
                         cookies: list = None) -> Dict:
        """
        并行生成：一个账号开多个标签页，每个标签页一条任务。
        Tab1 完整初始化（新对话→视频模式→模型→时长），
        Tab2..N 用 new_page()+goto chat URL（视频设置自动继承），传图+发提示词。
        全部发完后轮询所有标签页，检测出片→点封面→抓 vdl 直链。
        """
        tasks = tasks or []
        if fake.enabled():
            return self._fake_generate(tasks[:max_parallel], on_video_ready)
        result = {"success": [], "failed": [], "total": len(tasks), "videos": {}}
        p, context = None, None
        pages: list = []

        try:
            p, context, first_page = self._connect(profile_dir, cookies)
            if not self.check_login_status(first_page):
                raise Exception("账号未登录")

            # 并行时各标签页同时消耗，只能整体读：发送前一次、全部出片后一次，单条成本 = 差值 / 成功条数
            before = self._quota_now(first_page, refresh=False)
            if self._member_exhausted(before):
                raise Exception("会员额度已用完")

            active_tasks = tasks[:max_parallel]

            # --- Tab1: 完整初始化 ---
            logger.info("=== Tab1 初始化 ===")
            self.new_conversation(first_page)
            self.switch_to_video_mode(first_page)
            pages.append(first_page)

            # --- Tab1: 初始化 + 传图 + 发提示词（快速，不等确认）---
            t0 = active_tasks[0]
            imgs0 = [a for a in t0.get("assets", []) if a.lower().endswith(('.png','.jpg','.jpeg','.webp'))]
            if imgs0:
                self.upload_images(first_page, imgs0)
            self._send_prompt_fast(first_page, t0.get("prompt", ""))
            logger.info("分镜 %s 已发送 (tab1)", t0.get("shot_no"))
            self._push_status(t0.get("shot_no"), "generating", 60, "视频生成中...")

            # --- Tab2..N: 快速开标签页 + 切视频模式 + 传图 + 发提示词 ---
            for i, task in enumerate(active_tasks[1:], start=1):
                try:
                    pg = context.new_page()
                    pg.set_default_timeout(30000)
                    pg.goto("https://www.doubao.com/chat/")
                    self._wait_js(pg, "() => !!document.querySelector('[contenteditable=true]')", 8000)
                    self.switch_to_video_mode(pg)
                    imgs = [a for a in task.get("assets", []) if a.lower().endswith(('.png','.jpg','.jpeg','.webp'))]
                    if imgs:
                        self.upload_images(pg, imgs)
                    self._send_prompt_fast(pg, task.get("prompt", ""))
                    logger.info("分镜 %s 已发送 (tab%d)", task.get("shot_no"), i+1)
                    self._push_status(task.get("shot_no"), "generating", 60, "视频生成中...")
                    pages.append(pg)
                except Exception as e:
                    logger.error("分镜 %s 发送失败: %s", task.get("shot_no"), e)
                    result["failed"].append(task.get("shot_no"))
                    self._push_status(task.get("shot_no"), "failed", 0, "发送失败")

            # --- 快速轮询处理所有 tab 的确认 ---
            logger.info("全部 %d 条已发送，处理确认...", len(active_tasks))
            for _ in range(20):
                time.sleep(3)
                any_confirm = False
                for pg in pages:
                    try:
                        if self._handle_confirm_for(pg):
                            any_confirm = True
                    except Exception:
                        pass
                if not any_confirm:
                    break

            # --- 轮询所有 tab：抓直链→立即下载→回调写库 ---
            logger.info("等待出片...")
            done = {}  # shot_no -> video_path
            deadline = time.time() + 1200
            expected = len(active_tasks) - len(result["failed"])
            while len(done) < expected and time.time() < deadline:
                for idx, pg in enumerate(pages):
                    task = active_tasks[idx]
                    shot_no = task.get("shot_no")
                    if shot_no in done:
                        continue
                    try:
                        self._handle_confirm_for(pg)
                        src = self._read_video_src(pg)
                        if src and "vdl.doubao.com" in src:
                            logger.info("分镜 %s 抓到直链，立即下载", shot_no)
                            vp, frame = self.download_video(pg, src, shot_no)
                            if vp:
                                done[shot_no] = vp
                                result["success"].append(shot_no)
                                result["videos"][shot_no] = vp
                                if on_video_ready:
                                    try:
                                        on_video_ready(task.get("shot_id"), shot_no, vp, frame)
                                    except Exception as cb_err:
                                        logger.error("回调写库失败: %s", cb_err)
                                self._push_status(shot_no, "done", 100, "生成完成")
                            continue
                        if pg.evaluate(
                            """() => [...document.querySelectorAll('*')].some(el =>
                               el.children.length===0 && (el.textContent||'').includes('视频生成好了'))"""
                        ):
                            boxes = self._candidate_covers(pg)
                            if boxes:
                                self._click_first_cover(pg, boxes)
                    except Exception as e:
                        logger.debug("tab%d 轮询异常: %s", idx, e)
                time.sleep(5)

            for idx, pg in enumerate(pages):
                shot_no = active_tasks[idx].get("shot_no")
                if shot_no not in done and shot_no not in result["failed"]:
                    result["failed"].append(shot_no)
                    self._push_status(shot_no, "failed", 0, "超时未出片")

            after = self._quota_now(first_page, refresh=True)
            # 有失败（超时的可能稍后仍会扣额度）时差值不可靠，不记成本
            if result["success"] and not result["failed"]:
                self._record_cost(before, after, len(result["success"]))

            logger.info("并行批量完成: 成功%d, 失败%d",
                        len(result["success"]), len(result["failed"]))
        except Exception as e:
            logger.error("并行批量异常: %s", e)
            raise
        finally:
            if context:
                try:
                    self.last_cookies = self.export_cookies(context)
                    context.close()
                except Exception: pass
            if p:
                try: p.stop()
                except Exception: pass
        return result

    def _click_first_cover(self, page: Page, boxes: list):
        for box in boxes[:2]:
            try:
                page.mouse.click(box["cx"], box["cy"])
                time.sleep(3)
                for _ in range(6):
                    src = self._read_video_src(page)
                    if src and "vdl.doubao.com" in src:
                        return
                    time.sleep(2)
                page.keyboard.press("Escape")
            except Exception:
                pass

    def fire_prompts(self, profile_dir: str = "", tasks: List[Dict] = None,
                     cookies: list = None) -> Dict:
        """
        一个标签页快速连发：新对话 → 切视频模式 → 传图 → 发提示词，
        发完立刻下一个，不等出片。豆包服务端自己排队。
        """
        tasks = tasks or []
        result = {"sent": [], "failed": [], "total": len(tasks)}
        p, context, page = None, None, None
        try:
            p, context, page = self._connect(profile_dir, cookies, headless=False)
            if not self.check_login_status(page):
                raise Exception("账号未登录")

            for task in tasks:
                shot_no = task.get("shot_no", 0)
                prompt = task.get("prompt", "")
                assets = task.get("assets", [])
                try:
                    logger.info("=== 发送分镜 %s ===", shot_no)
                    self.new_conversation(page)
                    self.switch_to_video_mode(page)
                    images = [a for a in assets
                              if a.lower().endswith(('.png', '.jpg', '.jpeg', '.webp'))]
                    if images:
                        self.upload_images(page, images)
                    self.send_prompt(page, prompt)
                    result["sent"].append(shot_no)
                    logger.info("分镜 %s 已发送", shot_no)
                    time.sleep(2)
                except Exception as e:
                    logger.error("分镜 %s 发送失败: %s", shot_no, e)
                    result["failed"].append(shot_no)

            logger.info("发送完成: 成功%d, 失败%d", len(result["sent"]), len(result["failed"]))
        except Exception as e:
            logger.error("发送异常: %s", e)
            raise
        finally:
            if context:
                try:
                    self.last_cookies = self.export_cookies(context)
                    context.close()
                except Exception:
                    pass
            if p:
                try:
                    p.stop()
                except Exception:
                    pass
        return result
