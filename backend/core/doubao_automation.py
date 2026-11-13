"""
豆包视频生成自动化
流程：新对话 → 切视频模式 → 选模型（默认 Seedance 2.0 Fast）→ 设时长（分镜段时长）→ 传图 → 发提示词 → 等生成 → 下载视频

关键修复（2026-11-04）：
- 新建对话改为点「新对话」按钮，而不是刷新首页
- 视频直链监听挂在 context 上，发送前就开始抓
- 确认兜底改为轮询 60s，而不是只看一次
- 下载改用带登录 Cookie/Referer 的 context.request，兜底页面 fetch
- URL 过滤收紧为 vdl.doubao.com 白名单，避免误判接口 URL
- 识别额度耗尽，不再干等超时
"""
import os
import re
import time
import json
import base64
import logging
from pathlib import Path
from typing import List, Dict, Optional
from playwright.sync_api import sync_playwright, Page, BrowserContext

from core.providers import fake
from core.doubao_quota import DEFAULT_COST_KEY, QuotaWatcher, cost_between, cost_key, fake_quota
from core.video_slider import (DEFAULT_MAX_SECONDS, DEFAULT_MIN_SECONDS, DEFAULT_TRACK_RIGHT_X,
                               arrow_steps, clamp_duration, parse_duration_label, slider_x)
from utils.file_util import FileUtil

logger = logging.getLogger(__name__)

# 豆包视频直链的固定 host 特征（v26-vdl.doubao.com / v33-vdl.doubao.com 都含 vdl.doubao.com）
VIDEO_HOST_MARK = "vdl.doubao.com"
# 额度耗尽时豆包的回复特征
QUOTA_HINTS = ("免费体验套餐", "不可用于创作", "额度已用完", "升级正式订阅", "今日额度")
# 生成被拒绝/拦截时的回复特征（版权、违规、风控等），命中即停止等待、不再确认
REJECT_HINTS = ("版权限制", "更换输入内容", "更换内容", "内容违规", "违反", "无法生成",
                "生成失败", "请更换", "无法为你生成", "审核未通过", "涉嫌")
# 找不到确认按钮、只能打字时发的话。曾用「确认，开始生成」，被视频模型当字幕烧进画面底部；
# 现用不含画面词的指令句，并明确要求不加文字。旧文案仍在 _is_confirm_reply 里识别（兼容已发出的气泡）。
# 已确认后页面仍停在确认提示时，补发确认的冷却/次数上限；提示词发出后多久仍待确认则强制补发/判失败
RESEND_COOLDOWN = 45
MAX_CONFIRM_RESEND = 1  # 补发上限；任何情况下同一次生成最多发 MAX_CONFIRM_TOTAL 条确认
MAX_CONFIRM_TOTAL = 2
STUCK_CONFIRM_SECS = 150
STUCK_FAIL_GRACE_SECS = 60
CONFIRM_REPLY = "好的，就按以上内容直接生成，成片里不要加任何字幕和文字。"
LEGACY_CONFIRM_REPLY = "确认，开始生成"


def _is_confirm_reply(text: str) -> bool:
    t = text or ""
    return CONFIRM_REPLY in t or ("确认" in t and ("开始生成" in t or "确认生成" in t))


# 已进入生成中 / 已确认 / 已有结果的特征（出现后不再判定为待确认）
# 注意：不能收录"预计等待""开始生成视频"这类待确认承诺里也会出现的词，否则会漏确认
IN_PROGRESS_HINTS = ("正在渲染", "已启动视频生成", "正在生成视频",
                     "已确认，将为你生成", "视频生成好了", "你的视频",
                     # T-270：豆包真实受理回复的措辞（关键词只是补充，主判断是确认后是否出现了新的豆包回复）
                     "我将为你生成", "预计等待", "视频生成好后", "主动发送给你",
                     "优先生成通道", "消耗付费额度")
# 付费额度提示：只提示不阻止，不能当成额度耗尽
PAID_QUOTA_HINTS = ("消耗付费额度", "付费额度")
# 生成前要求确认的回复特征（确认卡片为纯文本，无按钮，只能打字回复）
CONFIRM_HINTS = ("确认后我再开始", "确认后再开始", "确认后开始生成", "确认生成",
                 "是否生成", "开始生成吗", "是否开始生成", "确认后我再开始生成视频")


def _is_video_url(url: str) -> bool:
    u = (url or "").lower()
    return VIDEO_HOST_MARK in u


# 消息 JSON 响应体里的视频直链字段 download_url（原始文本可能带 \" 转义）
_DOWNLOAD_URL_RE = re.compile(r'download_url\\?"\s*:\s*\\?"(https://[^"\\]+)')
# 消息体里的视频 vid（用于主动 POST 无水印接口换真无水印链）
# chain 体里 vid 是嵌套 JSON 字符串，引号常被双重转义成 \"vid\":\"xxx\"，兼容两种写法；
# 字段名兼容 vid / video_id / item_id（真实字段名待 chain body 留证核对后收敛）
_VID_RE = re.compile(r'(?:vid|video_id|item_id)\\?"\s*:\s*\\?"([^"\\,}]+)')
# 无水印接口（POST，body {"vid":[vid]}）；device_id/web_id 等浏览器参数非必需
_WM_API = ("https://www.doubao.com/creativity/resource/get_without_watermark"
           "?version_code=20800&language=zh&device_platform=web&aid=497858"
           "&real_aid=497858&pkg_type=release_version&region=CN&sys_region=CN"
           "&web_platform=browser&use-olympus-account=1")
# 只从当前对话消息流 / 无水印接口解析直链；batch_get 是会话列表，混有历史会话视频，不收
_BODY_API_TAGS = ("/im/chain/single", "get_without_watermark")


_LR_PARAM = re.compile(r"([?&])lr=[^&#]*")


# 封装里的编码 fourcc：hev1/hvc1 为 H.265(HEVC，剪映易报格式异常)，avc1 为 H.264
_HEVC_MARKS = (b"hev1", b"hvc1", b"hev2", b"hvc2")
_CODEC_MARKS = _HEVC_MARKS + (b"avc1", b"av01", b"mp4v")


def _detect_codec_fourcc(data: bytes) -> Optional[str]:
    """从 mp4 二进制扫描视频编码 fourcc；moov 可能在头部或尾部，两端各取 2MB。"""
    if not data:
        return None
    head = data[:2_000_000]
    tail = data[-2_000_000:] if len(data) > 4_000_000 else b""
    blob = head + tail
    for mark in _CODEC_MARKS:
        if mark in blob:
            return mark.decode()
    return None


def to_unwatermarked_url(url: str) -> str:
    """豆包视频直链（vdl.doubao.com）一律改成无水印版本：lr 参数不论原值是什么
    （video_gen_watermark_dyn 等）都改成 lr=unwatermarked，没有 lr 参数就补上；其他参数原样保留。
    非豆包直链原样返回。"""
    if not url or not _is_video_url(url):
        return url
    if _LR_PARAM.search(url):
        return _LR_PARAM.sub(r"\1lr=unwatermarked", url)
    base, sep, frag = url.partition("#")
    joiner = "&" if "?" in base else "?"
    return base + joiner + "lr=unwatermarked" + (sep + frag if sep else "")


_to_clean_url = to_unwatermarked_url  # 兼容旧名


class DoubaoVideoGenerator:
    """豆包视频生成器"""

    def __init__(self, project_root: str, status_callback=None):
        self.project_root = Path(project_root)
        # 与图片/音频共用 settings.STATIC_DIR（返回的 videos/xxx 由 /static 挂载对外提供）
        self.static_dir = FileUtil.get_static_dir()
        self.videos_dir = self.static_dir / "videos"
        self.videos_dir.mkdir(parents=True, exist_ok=True)
        self.images_dir = FileUtil.get_images_dir()
        # 本次会话抓到的所有视频直链（有序）；video_sources 记录每条来源接口
        self.video_urls: List[str] = []
        self.video_sources: Dict[str, str] = {}
        self.chain_vid: Optional[str] = None  # 消息流里最新视频的 vid，用于换无水印链
        self._wm_tried = False  # 本条是否已尝试过主动换无水印链（避免重复打接口）
        self._prompt_sent = False  # 本轮提示词是否已发出；发出前抓到的预览流标记为 pre 不可信
        self._pw = None
        self.context: Optional[BrowserContext] = None
        self.status_callback = status_callback  # 状态推送回调
        self.last_cookies: list = []  # 任务结束后回写用的最新 cookie
        # 会员额度：监听挂在 context 上，页面每次打开 /chat/ 都顺带拿到最新读数
        self.quota = QuotaWatcher()
        self.last_quota: Optional[dict] = None   # 最近一次额度读数（规范化），由调用方写回账号
        self.cost_samples: list = []             # 本次成功生成的单条消耗 [(成本分键, used 差值)]
        self.last_fail: Optional[dict] = None   # 最近一次抓直链失败的细分原因 {code,msg,conversation_url}
        self.last_duration: Optional[int] = None  # 最近一次设置后读回的时长（秒）
        self._cost_key = DEFAULT_COST_KEY         # 当前任务的成本分键（模型 + 时长）
        self._confirmed: set = set()  # 已确认过的 page（按 id），防止重复回复
        self._prompt_base: dict = {}  # page id -> 发送本轮提示词前自己发的气泡数
        self._prompt_sent_at: dict = {}  # page id -> 本轮提示词发送时间戳
        self._resend_count: dict = {}  # page id -> 已补发确认次数
        self._confirm_total: dict = {}  # page id -> 本次生成已发出的确认条数（含点按钮）
        self._confirm_snap: dict = {}  # page id -> 最近一次发确认前的 (豆包回复数, 消息总数)
        self._accepted: set = set()  # 确认后已出现豆包新回复的 page，视为已受理，不再补发
        self._paid_logged: set = set()
        self._confirmed_at: dict = {}  # page id -> 最近一次确认时间戳（冷却内不再发）

    @staticmethod
    def _mode_args(task: Dict) -> Dict:
        """任务里的视频模型与时长（由 api/video.py 按分镜段填入）；旧调用方不传时按 Fast + 15 秒。"""
        return {"duration": task.get("duration") or DEFAULT_MAX_SECONDS,
                "model_name": task.get("model_name") or "Seedance 2.0 Fast"}

    @staticmethod
    def _task_files(task: Dict) -> list:
        """可上传的参考素材：按模型接受的扩展名过滤（都不接受音频），最多 max_files 个。"""
        exts = tuple("." + e for e in (task.get("reference_types") or ["png", "jpg", "jpeg", "webp"]))
        files = [a for a in task.get("assets", []) if a.lower().endswith(exts)]
        return files[:int(task.get("max_files") or 10)]

    def _use_task(self, task: Dict):
        args = self._mode_args(task)
        self._cost_key = cost_key(args["model_name"], f"{clamp_duration(args['duration'])}s")

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
            except Exception as e:
                logger.warning("推送生成状态失败: %s", e)

    # ------------------------------------------------------------------ 连接
    def _remember_video(self, url: str, source: str):
        """登记一条视频直链（去重），落盘留档。"""
        if not url or url in self.video_urls:
            return
        # 提示词发出之前旁路被动监听到的播放器流，多为页面 banner/历史残留，不可信；
        # 打 pre 标记，兜底选链时排除。dom 是点开当前结果封面后主动读取的播放器 src，归属本次结果，不标记。
        if source == "direct" and not self._prompt_sent:
            source = "direct:pre"
        self.video_urls.append(url)
        self.video_sources[url] = source
        logger.info("抓到视频直链[%s]: %s", source, url)
        try:
            out_dir = self.project_root / "output_videos"
            out_dir.mkdir(parents=True, exist_ok=True)
            with open(out_dir / "_captured_urls.json", "a") as f:
                f.write(json.dumps({"ts": time.time(), "url": url, "source": source},
                                   ensure_ascii=False) + "\n")
        except Exception as e:
            logger.debug("直链落盘失败: %s", e)

    def _latest_video_url(self) -> Optional[str]:
        """取当前直链：无水印接口片源优先，其次本轮结果流。提示词发出前的 pre 残留流
        （页面 banner/历史残留）不参与成片兜底；若候选全是 pre，则视为无可信链。"""
        if not self.video_urls:
            return None
        fresh = [u for u in self.video_urls
                 if not self.video_sources.get(u, "").endswith(":pre")]
        if not fresh:
            return None

        def rank(u: str) -> int:
            s = self.video_sources.get(u, "")
            if "without_watermark" in s:
                return 0
            return 1

        return sorted(fresh, key=rank)[0]

    def _fetch_unwatermarked_url(self, vid: str) -> Optional[str]:
        """用 vid 主动 POST 无水印接口，换真无水印直链（另一条 CDN 片源）；失败返回 None。"""
        if not vid or not self.context:
            return None
        try:
            resp = self.context.request.post(
                _WM_API,
                data=json.dumps({"vid": [vid]}),
                headers={"Referer": "https://www.doubao.com/",
                         "Content-Type": "application/json"},
                timeout=30000,
            )
            if not resp.ok:
                logger.warning("无水印接口返回 %s", resp.status)
                return None
            body = resp.text()
            url = None
            try:
                data = resp.json()
                dv = (data.get("data") or {}).get("download_video") or {}
                item = dv.get(vid) or (next(iter(dv.values())) if dv else None)
                if isinstance(item, dict):
                    url = item.get("download_url")
            except Exception:
                url = None
            if not url:
                m = _DOWNLOAD_URL_RE.search(body)
                url = m.group(1) if m else None
            if url and _is_video_url(url):
                self._remember_video(url, "body:without_watermark")
                logger.info("主动换无水印链成功 vid=%s", vid)
                return url
        except Exception as e:
            logger.warning("主动换无水印链失败: %s", str(e)[:160])
        return None

    def _dump_chain_body(self, body: str):
        """chain 响应体未解析到 vid 时留证：截取片段落盘，便于核对真实视频标识字段名。"""
        try:
            out_dir = self.project_root / "output_videos"
            out_dir.mkdir(parents=True, exist_ok=True)
            ts = int(time.time())
            path = out_dir / f"chain_body_{ts}.json"
            path.write_text(
                json.dumps({"ts": ts, "body": (body or "")[:2000]}, ensure_ascii=False),
                encoding="utf-8")
            logger.info("chain body 留证: %s", path)
        except Exception as e:
            logger.debug("chain body 留证失败: %s", e)

    def _is_trusted_source(self, url: str) -> bool:
        """可信成片源：仅无水印接口返回的片源。播放器预览流(direct/dom)可能是
        页面 banner/历史残留，不能作为提前采信的成片。"""
        return "without_watermark" in self.video_sources.get(url, "")

    def _is_clean_source(self, url: str) -> bool:
        s = self.video_sources.get(url, "")
        if "without_watermark" in s:
            return True
        return "lr=unwatermarked" in (url or "")

    def _resolve_video_url(self, page: Page = None) -> Optional[str]:
        """返回最终下载用直链：chain 带水印链先用 vid 主动 POST 无水印接口换片源；
        换不到再兜底原链。"""
        best = self._latest_video_url()
        if not best:
            return None
        if self._is_clean_source(best):
            return best
        if self.chain_vid and not self._wm_tried:
            self._wm_tried = True
            wm = self._fetch_unwatermarked_url(self.chain_vid)
            if wm:
                return wm
        logger.warning("无水印片源不可得，兜底使用带水印链: %s", best[:120])
        return best

    def _wait_clean_url(self, page: Page = None, seconds: int = 8) -> Optional[str]:
        """已有候选但当前最佳是带水印流时，短窗口等待前端自发拉取的无水印片源；
        窗口内出现 clean/trusted 片源立即返回，超时再走 resolve 兜底原链。"""
        best = self._latest_video_url()
        if not best:
            return None
        if self._is_clean_source(best):
            return self._resolve_video_url(page)
        deadline = time.time() + seconds
        while time.time() < deadline:
            time.sleep(1.5)
            best = self._latest_video_url()
            if best and self._is_clean_source(best):
                return self._resolve_video_url(page)
            # 等待期间若后续才解析到 vid，主动尝试换一次无水印链
            if self.chain_vid and not self._wm_tried:
                return self._resolve_video_url(page)
        return self._resolve_video_url(page)

    def _scroll_cover_into_view(self, page: Page, box: dict) -> Optional[dict]:
        """把候选封面滚到视口中部，避开底部固定输入框遮挡；返回更新后的中心坐标。"""
        try:
            return page.evaluate(
                """(box) => {
                    const imgs = [...document.querySelectorAll('img')];
                    let best = null, bestD = 1e9;
                    for (const im of imgs) {
                        const r = im.getBoundingClientRect();
                        if (!(r.width > 240 && r.height > 120)) continue;
                        const cx = r.left + r.width/2, cy = r.top + r.height/2;
                        const d = Math.abs(cx - box.cx) + Math.abs(cy - box.cy);
                        if (d < bestD) { bestD = d; best = im; }
                    }
                    if (!best) return null;
                    best.scrollIntoView({block: 'center', inline: 'center'});
                    const r = best.getBoundingClientRect();
                    return {cx: r.left + r.width/2, cy: r.top + r.height/2};
                }""",
                box,
            )
        except Exception:
            return None

    def _attach_response_listener(self, context: BrowserContext):
        def _on_response(resp):
            try:
                u = resp.url
                # 1) 播放器直接拉流的 vdl 请求
                if _is_video_url(u) and resp.status in (200, 206):
                    self._remember_video(u, "direct")
                    return
                # 2) 消息/无水印接口的 JSON 响应体里带 download_url（封面阶段不会拉流，
                #    直连监听抓不到，必须解析响应体）。只收当前对话消息流与无水印接口，
                #    会话列表 batch_get 混有历史会话视频，跳过。
                if any(tag in u for tag in _BODY_API_TAGS):
                    try:
                        body = resp.text()
                    except Exception:
                        return
                    tag = "body:without_watermark" if "without_watermark" in u else "body:chain"
                    if tag == "body:chain":
                        vm = _VID_RE.search(body)
                        if vm:
                            self.chain_vid = vm.group(1)
                            logger.info("chain 体解析到 vid=%s", self.chain_vid)
                        elif _DOWNLOAD_URL_RE.search(body):
                            n = len(_DOWNLOAD_URL_RE.findall(body))
                            logger.warning("chain 体未解析到 vid（body 含 %d 条 download_url），片段已落盘留证", n)
                            self._dump_chain_body(body)
                    for mu in _DOWNLOAD_URL_RE.findall(body):
                        if _is_video_url(mu):
                            self._remember_video(mu, tag)
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
        # 新对话：清掉上一条的确认标记，允许本次重新确认一次
        self._confirmed.discard(id(page))
        self._confirmed_at.pop(id(page), None)
        # 清空上一页/页面 banner 残留的视频候选，避免把历史或推荐流当成本次成片
        self.video_urls.clear()
        self.video_sources.clear()
        self.chain_vid = None
        self._wm_tried = False
        self._prompt_sent = False
        # 等输入框就绪
        self._wait_js(page,
            "() => !!document.querySelector('[contenteditable=true]')", 8000)

    def switch_to_video_mode(self, page: Page, duration=DEFAULT_MAX_SECONDS,
                             model_name: str = "Seedance 2.0 Fast"):
        """切换到视频生成模式，选模型（默认 Seedance 2.0 Fast），时长设为 duration 秒（分镜段的时长）。"""
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

        # 选模型（项目设置，默认 Seedance 2.0 Fast）
        self._select_model(page, model_name)

        # 设时长：按段时长拖滑块，读回校验；失败退回 15s
        self.last_duration = self._set_duration(page, duration)
        logger.info("已切换到视频生成模式（%s，%ss）", model_name, self.last_duration or "?")

    def _select_model(self, page: Page, model_name: str):
        try:
            page.click('button:has-text("Seedance")', timeout=5000)
            # 精确匹配名字：Seedance 2.0 是 Seedance 2.0 Fast 的前缀，不能用 has-text
            found = self._wait_js(page,
                f"""() => [...document.querySelectorAll('*')].some(el =>
                   (el.textContent || '').trim() === {model_name!r})""", 3000)
            clicked = found and page.evaluate(
                """(name) => {
                    const els = [...document.querySelectorAll('*')].filter(el =>
                        (el.textContent || '').trim() === name && el.getBoundingClientRect().width > 0);
                    const el = els[els.length - 1];
                    if (!el) return false;
                    el.click();
                    return true;
                }""", model_name)
            if not clicked:
                raise RuntimeError("菜单里没有 " + model_name)
        except Exception as e:
            logger.warning("未切换到模型 %s（%s），沿用当前默认模型", model_name, e)

    def _read_slider(self, page: Page) -> dict:
        """读滑块：当前值（aria-valuenow 或按钮上的“15s”）、范围、轨道左右端、拇指中心。"""
        return page.evaluate(
            r"""() => {
                const el = document.querySelector('[role=slider]');
                const out = {};
                if (el) {
                    const r = el.getBoundingClientRect();
                    out.x = r.x + r.width / 2; out.y = r.y + r.height / 2;
                    out.now = el.getAttribute('aria-valuenow');
                    out.min = el.getAttribute('aria-valuemin');
                    out.max = el.getAttribute('aria-valuemax');
                    // 轨道：往上找第一个明显比拇指宽的祖先
                    let p = el.parentElement;
                    while (p && p.getBoundingClientRect().width < r.width * 4) p = p.parentElement;
                    if (p) { const t = p.getBoundingClientRect(); out.left = t.left; out.right = t.right; }
                }
                for (const b of document.querySelectorAll('button,[role=button]')) {
                    const t = (b.innerText || '').trim();
                    if (/^\d+(\.\d+)?\s*(s|秒)$/i.test(t)) { out.label = t; break; }
                }
                return out;
            }"""
        ) or {}

    @staticmethod
    def _slider_value(info: dict):
        try:
            return int(round(float(info.get("now"))))
        except (TypeError, ValueError):
            return parse_duration_label(info.get("label") or "")

    def _drag_slider(self, page: Page, info: dict, x: float):
        page.mouse.move(info["x"], info["y"])
        page.mouse.down()
        time.sleep(0.2)
        page.mouse.move(x, info["y"], steps=25)
        time.sleep(0.4)
        page.mouse.up()
        time.sleep(0.6)

    def _set_duration(self, page: Page, duration) -> Optional[int]:
        """把时长滑块设到 duration 秒（待真机验证）。

        先按轨道位置换算横坐标拖过去（core/video_slider.slider_x），读回 aria-valuenow / 按钮文字；
        差几格就用方向键补；仍不对则退回 15s（拖到最右）并记日志。返回最终读到的秒数（读不到为 None）。
        """
        try:
            page.click('button:has-text("自动")', timeout=4000)
        except Exception:
            # 已经设过时长时按钮显示的是“15s”之类
            try:
                page.click('button:has-text("s")', timeout=2000)
            except Exception:
                pass
        try:
            self._wait_js(page, "() => !!document.querySelector('[role=slider]')", 4000)
            info = self._read_slider(page)
            if not info.get("x"):
                raise RuntimeError("没有找到时长滑块")
            vmin = float(info["min"]) if info.get("min") not in (None, "") else DEFAULT_MIN_SECONDS
            vmax = float(info["max"]) if info.get("max") not in (None, "") else DEFAULT_MAX_SECONDS
            target = clamp_duration(duration, vmin, vmax)
            x = slider_x(target, info.get("left"), info.get("right"), vmin, vmax)
            self._drag_slider(page, info, x)
            got = self._slider_value(self._read_slider(page))
            steps = arrow_steps(got, target)
            if steps:
                page.focus('[role=slider]')
                key = "ArrowRight" if steps > 0 else "ArrowLeft"
                for _ in range(abs(steps)):
                    page.keyboard.press(key)
                    time.sleep(0.05)
                time.sleep(0.4)
                got = self._slider_value(self._read_slider(page))
            if got != target:
                logger.warning("时长滑块设为 %ss 失败（读回 %s），退回 15s", target, got)
                info = self._read_slider(page)
                self._drag_slider(page, info, info.get("right") or DEFAULT_TRACK_RIGHT_X)
                got = self._slider_value(self._read_slider(page))
            logger.info("时长设置结果: 目标 %ss，读回 %s", target, got)
            page.keyboard.press("Escape")
            return got
        except Exception as e:
            logger.warning("时长滑块设置失败（%s），沿用默认时长", e)
            return None

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
        self._prompt_sent = True
        logger.info("提示词已发送")

    def _in_progress(self, page: Page) -> bool:
        """页面已进入生成中 / 已确认 / 已有结果，不再判定为待确认。"""
        return self._page_contains(page, IN_PROGRESS_HINTS)

    def _sent_texts(self, page: Page) -> list:
        """页面上自己发送的全部气泡文本（按从上到下顺序）。"""
        try:
            r = page.evaluate(
                """() => [...document.querySelectorAll('[class*="send-msg-bubble"]')]
                    .map(b => (b.innerText || '').trim())"""
            )
            return list(r) if isinstance(r, (list, tuple)) else []
        except Exception:
            return []

    def _last_sent_text(self, page: Page) -> str:
        """最下面一条自己发送的气泡文本。"""
        try:
            return page.evaluate(
                """() => {
                    const bubbles = [...document.querySelectorAll('[class*="send-msg-bubble"]')];
                    if (!bubbles.length) return '';
                    return (bubbles[bubbles.length - 1].innerText || '').trim();
                }"""
            )
        except Exception:
            return ""

    def _s(self, name: str, factory):
        """按需创建的每页状态容器（兼容绕过 __init__ 构造的实例）。"""
        if name not in self.__dict__:
            self.__dict__[name] = factory()
        return self.__dict__[name]

    def _chat_messages(self, page: Page) -> list:
        """按 DOM 顺序返回页面所有消息 [{role: 'send'|'recv', text}]；取不到返回 []。"""
        try:
            r = page.evaluate(
                """() => { /* __chat_messages__ */
                    const sel = '[class*="send-msg-bubble"], [class*="receive-msg"], [class*="receive-message"], '
                        + '[data-testid="receive_message"], [data-testid="message_text_content"]';
                    const out = [];
                    for (const el of document.querySelectorAll(sel)) {
                        if (el.parentElement && el.parentElement.closest(sel)) continue;
                        const cls = String(el.className || '');
                        out.push({role: cls.includes('send-msg-bubble') ? 'send' : 'recv',
                                  text: (el.innerText || '').trim()});
                    }
                    return out;
                }"""
            )
            return [m for m in r if isinstance(m, dict)] if isinstance(r, (list, tuple)) else []
        except Exception:
            return []

    def _msg_counts(self, page: Page) -> tuple:
        msgs = self._chat_messages(page)
        return sum(1 for m in msgs if m.get("role") == "recv"), len(msgs)

    def _reply_after_confirm(self, page: Page) -> bool:
        """自上一次发确认以来页面是否出现了新的豆包回复（按消息数量/最后一条消息角色，不看措辞）。"""
        pid = id(page)
        if pid in self._s("_accepted", set):
            return True
        snap = self._s("_confirm_snap", dict).get(pid)
        if snap is None:
            return False
        recv0, total0 = snap
        msgs = self._chat_messages(page)
        recv = sum(1 for m in msgs if m.get("role") == "recv")
        if recv > recv0 or (msgs and msgs[-1].get("role") == "recv" and len(msgs) > total0):
            self._s("_accepted", set).add(pid)
            self._stage("CONFIRM_ACCEPTED", "确认之后豆包已有新回复，视为已受理，不再补发确认，等待渲染")
            return True
        return False

    def _note_paid_quota(self, page: Page):
        """回复里含「免费额度已用完…消耗付费额度」：只打一条提示，不阻止生成。"""
        pid = id(page)
        if pid in self._s("_paid_logged", set):
            return
        if any("付费额度" in c for c in self._quota_contexts(page)):
            self._s("_paid_logged", set).add(pid)
            self._stage("PAID_QUOTA", "今日免费额度已用完，本次将消耗付费额度（仅提示，继续生成）")

    def _confirm_sent_after_prompt(self, page: Page) -> bool:
        """本轮提示词气泡之后，是否已出现确认语气泡。

        复用旧对话时最后一条自己发的气泡可能是上一轮的确认语，不能当成本轮已确认：
        只认 send_prompt 发送前记录的气泡数之后新增的气泡，且需有提示词气泡本身（base 之后至少 2 条里的确认语）。
        没有基线记录（未经 send_prompt）时无法判断，一律视为未确认。
        """
        base = getattr(self, "_prompt_base", {}).get(id(page))
        if base is None:
            return False
        texts = self._sent_texts(page)
        # texts[base] 是本轮提示词气泡，确认语必须在它之后
        return any(_is_confirm_reply(t) for t in texts[base + 1:])

    def _confirm_present(self, page: Page) -> bool:
        """检测页面是否出现生成前确认提示；已在生成中/已有结果时不再视为待确认。"""
        if self._in_progress(page) or self._reply_after_confirm(page):
            return False
        return self._page_contains(page, CONFIRM_HINTS)

    def _handle_confirm_for(self, page: Page) -> bool:
        """检查页面是否要求确认，是则回复。返回本次是否发出了确认。

        首次确认冷却 20s；已确认过的对话若页面仍停在确认提示，超过 RESEND_COOLDOWN 后自愈补发（有次数上限）。
        """
        pid = id(page)
        now = time.time()
        last = self._confirmed_at.get(pid, 0)
        resend = pid in self._confirmed
        if resend:
            if now - last < RESEND_COOLDOWN or self._resend_count.get(pid, 0) >= MAX_CONFIRM_RESEND:
                return False
            if self._s("_confirm_total", dict).get(pid, 0) >= MAX_CONFIRM_TOTAL or self._reply_after_confirm(page):
                return False
        elif now - last < 20:
            return False
        if self._in_progress(page):
            return False
        if not resend and self._confirm_sent_after_prompt(page):
            logger.info("本轮提示词之后已发过确认，跳过重复回复")
            self._confirmed.add(pid)
            self._confirmed_at.setdefault(pid, now)
            return False
        if not self._confirm_present(page):
            return False
        if resend:
            self._resend_count[pid] = self._resend_count.get(pid, 0) + 1
            self._stage("CONFIRM_RESEND", f"页面仍停在待确认，补发确认（第 {self._resend_count[pid]} 次）")
        logger.info("检测到确认要求，自动回复")
        self._do_confirm(page, force=resend)
        self._confirmed.add(pid)
        self._confirmed_at[pid] = time.time()
        time.sleep(3)
        return True

    def send_prompt(self, page: Page, prompt: str):
        """输入提示词并发送，必须等到确认被处理或真正开始渲染才返回。"""
        # 发送前记录自己发的气泡数：之后出现在本轮提示词气泡之后的确认语才算本轮已确认
        self._prompt_base[id(page)] = len(self._sent_texts(page))
        self._prompt_sent_at[id(page)] = time.time()
        self._resend_count.pop(id(page), None)
        self._s("_confirm_total", dict).pop(id(page), None)
        self._s("_confirm_snap", dict).pop(id(page), None)
        self._s("_accepted", set).discard(id(page))
        self._s("_paid_logged", set).discard(id(page))
        page.evaluate(
            """(text) => {
                const ed = document.querySelector('[contenteditable=true]');
                if (ed) { ed.focus(); document.execCommand('insertText', false, text); }
            }""",
            prompt,
        )
        time.sleep(0.5)
        page.keyboard.press("Enter")
        self._prompt_sent = True
        logger.info("提示词已发送")

        # 新一轮提示词：重置该对话的确认态，允许本次重新确认一次
        self._confirmed.discard(id(page))
        self._confirmed_at.pop(id(page), None)

        # 最多等 120s：等"确认生成吗"出现并处理，或检测到真正开始渲染
        for _ in range(40):
            time.sleep(3)
            # 统一走带防连发/冷却/进行中否决的确认处理
            self._handle_confirm_for(page)
            # 确认后或无需确认时，检测渲染开始
            if self._in_progress(page):
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

    def _do_confirm(self, page: Page, force: bool = False):
        """优先点页面上的确认按钮/选项，点不到再打字回复。"""
        pid = id(page)
        if self._s("_confirm_total", dict).get(pid, 0) >= MAX_CONFIRM_TOTAL:
            logger.warning("本次生成已发 %d 条确认，达上限，不再发送", self._s("_confirm_total", dict).get(pid, 0))
            return
        self._s("_confirm_snap", dict)[pid] = self._msg_counts(page)
        self._s("_confirm_total", dict)[pid] = self._s("_confirm_total", dict).get(pid, 0) + 1
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
            self._stage("CONFIRM_SENT", "已点击确认按钮")
            return
        # 兜底：打字回复（输入框若已含确认文本则不再重复插入）
        already = page.evaluate(
            """() => {
                const ed = document.querySelector('[contenteditable=true]');
                return ed ? (ed.innerText || '') : '';
            }"""
        )
        if _is_confirm_reply(already) or "确认" in (already or "") or "开始生成" in (already or ""):
            logger.info("输入框已含确认文本，直接回车发送")
            page.keyboard.press("Enter")
            self._stage("CONFIRM_SENT", "输入框已有确认文本，已回车发送")
            time.sleep(2)
            return
        # 本轮提示词之后已发过确认语则不连发（补发 force 时放行）；上一轮的确认语不算
        if not force:
            if getattr(self, "_prompt_base", {}).get(id(page)) is None:
                # 没有本轮基线（未经 send_prompt 调用）：退回看最后一条气泡
                if _is_confirm_reply(self._last_sent_text(page)):
                    logger.info("最近气泡已是确认语，跳过重复发送")
                    self._s("_confirm_total", dict)[pid] -= 1
                    return
            elif self._confirm_sent_after_prompt(page):
                logger.info("本轮已有确认气泡，跳过重复发送")
                self._s("_confirm_total", dict)[pid] -= 1
                return
        page.evaluate(
            """(txt) => {
                const ed = document.querySelector('[contenteditable=true]');
                if (ed) { ed.focus(); document.execCommand('insertText', false, txt); }
            }""",
            CONFIRM_REPLY,
        )
        page.keyboard.press("Enter")
        logger.info("已打字回复确认语：%s", CONFIRM_REPLY)
        self._stage("CONFIRM_SENT", f"已打字回复确认语：{CONFIRM_REPLY}")
        time.sleep(2)

    # ------------------------------------------------------------------ 等待与抓 URL
    def _quota_contexts(self, page: Page) -> list:
        """含额度类关键词的叶子节点，连同其所在段落文本（≤400 字的最近祖先）一并返回。"""
        r = page.evaluate(
            """(hints) => {
                const out = [];
                for (const el of document.querySelectorAll('*')) {
                    if (el.children.length !== 0) continue;
                    const t = el.textContent || '';
                    if (!hints.some(h => t.includes(h))) continue;
                    let ctx = t, p = el.parentElement;
                    for (let i = 0; i < 4 && p; i++, p = p.parentElement) {
                        const pt = p.textContent || '';
                        if (pt.length > 400) break;
                        ctx = pt;
                    }
                    out.push(ctx);
                }
                return out;
            }""",
            list(QUOTA_HINTS) + list(PAID_QUOTA_HINTS),
        )
        return [c for c in r if isinstance(c, str)] if isinstance(r, (list, tuple)) else []

    def _quota_blocked(self, page: Page) -> bool:
        """额度耗尽。「免费额度已用完，本次将消耗付费额度」是继续生成，不算耗尽。"""
        for ctx in self._quota_contexts(page):
            if any(h in ctx for h in QUOTA_HINTS) and not any(h in ctx for h in PAID_QUOTA_HINTS):
                return True
        return False

    def _rejected(self, page: Page) -> bool:
        """生成被版权/违规/风控拒绝，命中即停止等待、不再确认。"""
        return self._page_contains(page, REJECT_HINTS)

    # ---- 阶段标签：日志里每个阶段一行 "[DOUBAO_STAGE] <TAG> ..."，供外部监听 ----
    # 生成中：WAITING_CONFIRM / GENERATING
    # 已完成待抓取：READY_PENDING_URL / FETCH_SCROLL / FETCH_COVER / RETRY_REFRESH
    # 成功：GOT_URL
    # 确认：CONFIRM_SENT（已发出确认）/ CONFIRM_RESEND（页面仍待确认，补发）
    # 真失败：FAILED_REJECTED / FAILED_QUOTA / FAILED_TIMEOUT / FAILED_NO_URL / FAILED_CONFIRM
    def _stage(self, tag: str, msg: str = ""):
        logger.info("[DOUBAO_STAGE] %s %s", tag, msg)

    def _fail(self, code: str, msg: str, conv_url: str = ""):
        """记录真失败原因（code=REJECTED/QUOTA/TIMEOUT/NO_URL），给调用方写错误信息与 SSE。"""
        self.last_fail = {"code": code, "msg": msg, "conversation_url": conv_url}
        self._stage("FAILED_" + code, msg)

    @staticmethod
    def _page_url(page: Page) -> str:
        try:
            return page.url or ""
        except Exception:
            return ""

    def _focus_chat_area(self, page: Page):
        """把鼠标移到聊天滚动容器中央（滚轮只作用于鼠标下面的容器）。"""
        cx, cy = 640, 400
        try:
            pos = page.evaluate(
                """() => {
                    let best = null, bestArea = 0;
                    document.querySelectorAll('*').forEach(el => {
                        const s = getComputedStyle(el);
                        if (!/(auto|scroll)/.test(s.overflowY)) return;
                        if (el.scrollHeight <= el.clientHeight + 4) return;
                        const r = el.getBoundingClientRect();
                        const area = r.width * r.height;
                        if (r.width > 300 && area > bestArea) { best = r; bestArea = area; }
                    });
                    if (best) return {x: best.left + best.width / 2, y: best.top + best.height / 2};
                    return {x: window.innerWidth / 2, y: window.innerHeight / 2};
                }"""
            )
            if pos:
                cx, cy = pos["x"], pos["y"]
        except Exception:
            pass
        try:
            page.mouse.move(cx, cy)
        except Exception:
            pass

    def _click_back_to_bottom(self, page: Page) -> bool:
        """点右下角「回到底部」箭头（若有）。"""
        try:
            return bool(page.evaluate(
                """() => {
                    const keys = ['回到底部', '回到最新', '滚动到底部', '回到最新消息', 'scroll-to-bottom', 'back-to-bottom'];
                    for (const el of document.querySelectorAll('button, [role=button], div, span')) {
                        const t = (el.getAttribute('aria-label') || el.getAttribute('title') || '') +
                                  ' ' + (el.className && el.className.toString ? el.className.toString() : '') +
                                  ' ' + (el.children.length === 0 ? (el.textContent || '') : '');
                        if (keys.some(k => t.includes(k))) {
                            const r = el.getBoundingClientRect();
                            if (r.width > 0 && r.height > 0) { el.click(); return true; }
                        }
                    }
                    return false;
                }"""
            ))
        except Exception:
            return False

    def _scroll_chat_to_bottom(self, page: Page):
        """滚到聊天底部：先聚焦聊天区，优先点「回到底部」，再滚轮+脚本兜底，等封面挂载。"""
        self._focus_chat_area(page)
        if self._click_back_to_bottom(page):
            self._stage("FETCH_SCROLL", "已点击「回到底部」")
            time.sleep(1)
        for _ in range(4):
            try:
                page.mouse.wheel(0, 1500)
            except Exception:
                pass
            time.sleep(0.8)
        try:
            page.evaluate(
                """() => {
                    document.querySelectorAll('*').forEach(el => {
                        const s = getComputedStyle(el);
                        if (/(auto|scroll)/.test(s.overflowY) && el.scrollHeight > el.clientHeight + 4)
                            el.scrollTop = el.scrollHeight;
                    });
                }"""
            )
        except Exception:
            pass
        time.sleep(2)

    def _grab_video_url(self, page: Page, label: str = "首轮") -> Optional[str]:
        """已提示生成好后抓直链一轮：滚到底 → 等封面挂载 → 从下往上点封面；旁路监听的直链随时命中。"""
        self._stage("FETCH_SCROLL", f"{label}：滚到聊天底部")
        self._scroll_chat_to_bottom(page)
        if self.video_urls:
            return self._wait_clean_url(page, 5)

        boxes = []
        for _ in range(30):
            boxes = self._candidate_covers(page)
            if boxes or self.video_urls:
                break
            # 虚拟列表按需渲染：封面没挂载就再滚一次
            self._focus_chat_area(page)
            try:
                page.mouse.wheel(0, 1500)
            except Exception:
                pass
            time.sleep(1)
        if self.video_urls:
            return self._wait_clean_url(page, 5)

        self._stage("FETCH_COVER", f"{label}：候选封面 {len(boxes)} 个")
        for box in boxes:
            centered = self._scroll_cover_into_view(page, box)
            if centered:
                box = centered
            for _attempt in range(3):
                # 先悬停：触发前端拉取无水印地址 / 视频流
                try:
                    page.mouse.move(box["cx"], box["cy"], steps=5)
                except Exception:
                    pass
                time.sleep(3)
                if self.video_urls:
                    return self._wait_clean_url(page, 5)
                # 再点击兜底，打开预览面板
                try:
                    page.mouse.click(box["cx"], box["cy"])
                except Exception:
                    continue
                time.sleep(3)
                for _ in range(10):
                    if self.video_urls:
                        return self._resolve_video_url(page)
                    src = self._read_video_src(page)
                    if src and "vdl.doubao.com" in src:
                        self._remember_video(src, "dom")
                        return self._resolve_video_url(page)
                    time.sleep(2)
            try:
                page.keyboard.press("Escape")
            except Exception:
                pass
            time.sleep(1)
        return self._wait_clean_url(page, 5)

    def wait_for_video(self, page: Page, timeout: int = 1200) -> Optional[str]:
        """等生成完成并返回视频直链；失败时原因写在 self.last_fail（code/msg/conversation_url）。"""
        self.last_fail = None
        self._stage("WAITING_CONFIRM", f"等待视频生成（最多 {timeout} 秒）")
        start = time.time()
        confirmed = False
        forced_at = None
        generating_logged = False
        text_seen_at = None

        while time.time() - start < timeout:
            if self.video_urls:
                resolved = self._resolve_video_url(page)
                # 只有无水印接口片源才提前返回；预览流(direct/dom)继续等结果就绪后兜底取链
                if resolved and self._is_trusted_source(resolved):
                    self._stage("GOT_URL", "旁路监听已抓到无水印直链")
                    return resolved
            if self._quota_blocked(page):
                self._fail("QUOTA", "账号额度/套餐不足，停止等待", self._page_url(page))
                return None
            self._note_paid_quota(page)
            if self._rejected(page):
                self._fail("REJECTED", "生成被拒绝（版权/违规/风控），停止等待，不再确认", self._page_url(page))
                return None
            # 流式输出可能在 send_prompt 的 90s 窗口之后才打出确认行，等待期内兜底
            if self._handle_confirm_for(page):
                confirmed = True
            # 兜底：提示词发出 STUCK_CONFIRM_SECS 后仍无渲染迹象且停在确认提示 -> 强制补确认；补完仍无效则明确失败
            sent_at = self._prompt_sent_at.get(id(page), start)
            stuck_for = time.time() - sent_at
            if stuck_for >= STUCK_CONFIRM_SECS and not self._in_progress(page) and self._confirm_present(page):
                total = self._s("_confirm_total", dict).get(id(page), 0)
                if forced_at is None and total < MAX_CONFIRM_TOTAL:
                    forced_at = time.time()
                    self._stage("CONFIRM_RESEND", f"提示词已发 {int(stuck_for)}s 仍停在待确认，强制补发确认")
                    self._do_confirm(page, force=True)
                    self._confirmed.add(id(page))
                    self._confirmed_at[id(page)] = time.time()
                    confirmed = True
                elif time.time() - self._confirmed_at.get(id(page), forced_at or 0) >= STUCK_FAIL_GRACE_SECS:
                    conv = self._page_url(page)
                    self._fail("CONFIRM", f"已发 {total} 条确认后页面仍停在待确认，对话：{conv or '（未取得对话链接）'}", conv)
                    return None
            if not generating_logged and (confirmed or self._in_progress(page)):
                generating_logged = True
                self._stage("GENERATING", "已确认，豆包渲染中")
            # 以结果封面/播放器真实挂载为就绪条件；完成文本可能先于封面流式打出，
            # 文本出现超过 20s 仍未识别到封面则兜底进入抓取流程（抓取内部会再等封面）
            try:
                if self._result_ready(page):
                    logger.info("结果封面/播放器已挂载")
                    break
                if self._page_contains(page, ("视频生成好了", "你的视频")):
                    if text_seen_at is None:
                        text_seen_at = time.time()
                        logger.info("页面提示视频已生成，等待结果封面挂载...")
                    elif time.time() - text_seen_at >= 20:
                        break
            except Exception:
                pass
            time.sleep(3)
        else:
            self._fail("TIMEOUT", f"等待视频生成超时（{timeout} 秒）", self._page_url(page))
            return self._resolve_video_url(page)

        conv_url = self._page_url(page)
        self._stage("READY_PENDING_URL", f"视频已生成，开始抓直链 对话={conv_url}")
        time.sleep(3)
        if self.video_urls:
            self._stage("GOT_URL", "旁路监听已抓到直链")
            return self._wait_clean_url(page, 8)

        url = self._grab_video_url(page, "首轮")
        if not url and conv_url:
            # 兜底：用该对话 URL 重新打开页面，再抓一轮
            self._stage("RETRY_REFRESH", f"首轮没抓到，刷新对话重试 {conv_url}")
            try:
                page.goto(conv_url)
                self._wait_js(page, "() => document.querySelectorAll('img').length > 0", 15000)
                time.sleep(3)
            except Exception as e:
                logger.warning("刷新对话页失败: %s", e)
            url = self._grab_video_url(page, "刷新后")
        if url:
            self._stage("GOT_URL", url)
            return url

        # 失败留证
        try:
            out_dir = self.project_root / "output_videos"
            out_dir.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(out_dir / f"novideo_{int(time.time())}.png"))
        except Exception:
            pass
        self._fail("NO_URL",
                   f"视频已生成但没抓到直链，可去豆包对话手动下载：{conv_url or '（未取得对话链接）'}",
                   conv_url)
        return None

    def _result_ready(self, page: Page) -> bool:
        """结果是否真正挂载：播放器 video 已出现，或结果封面卡片已渲染。
        不能只靠"视频生成好了"文本判定——完成文本可能先于封面流式打出。"""
        try:
            return page.evaluate(
                """() => {
                    if (document.querySelector('video[src^="http"], video source[src^="http"]')) return true;
                    const imgs = [...document.querySelectorAll('img')];
                    return imgs.some(im => {
                        const r = im.getBoundingClientRect();
                        if (!(r.width > 240 && r.height > 120)) return false;
                        const cls = (im.className || '').toString();
                        if (cls.includes('cover-')) return true;
                        let el = im.parentElement;
                        for (let k = 0; k < 4 && el; k++) {
                            if ((el.className || '').toString().includes('block-video-')) return true;
                            el = el.parentElement;
                        }
                        return false;
                    });
                }"""
            )
        except Exception:
            return False

    def _candidate_covers(self, page: Page) -> list:
        """候选封面图：宽>160的大图，结果卡片（cover-/block-video-）优先，其余大图兜底；
        按位置从下到上排序（最新消息在最下面）；视口外的先滚进来。"""
        try:
            boxes = page.evaluate(
                """() => {
                    const els = [...document.querySelectorAll('img')].filter(im => {
                        const r = im.getBoundingClientRect();
                        return r.width > 160 && r.height > 90;
                    });
                    const inView = r => r.bottom > 0 && r.top < window.innerHeight;
                    // 全在视口外：把最下面一张滚进视口
                    if (els.length && !els.some(im => inView(im.getBoundingClientRect()))) {
                        els.sort((a, b) => b.getBoundingClientRect().top - a.getBoundingClientRect().top);
                        els[0].scrollIntoView({block: 'center'});
                    }
                    const result = [], other = [];
                    els.forEach(im => {
                        const r = im.getBoundingClientRect();
                        if (!inView(r)) return;
                        const cls = (im.className || '').toString();
                        let inResult = cls.includes('cover-');
                        let el = im.parentElement;
                        for (let k = 0; k < 4 && el && !inResult; k++) {
                            if ((el.className || '').toString().includes('block-video-')) inResult = true;
                            el = el.parentElement;
                        }
                        const box = {cx: r.left + r.width/2, cy: r.top + r.height/2,
                                     area: r.width * r.height, is_result: inResult};
                        (inResult ? result : other).push(box);
                    });
                    result.sort((a, b) => b.cy - a.cy);
                    other.sort((a, b) => b.cy - a.cy);
                    return result.concat(other);  // 结果封面优先，其余大图兜底
                }"""
            )
            return boxes or []
        except Exception:
            return []

    def _read_video_src(self, page: Page) -> Optional[str]:
        try:
            return page.evaluate(
                """() => {
                    const vids = [...document.querySelectorAll('video')];
                    const http = v => { const s = v.currentSrc || v.src || ''; return s.startsWith('http') ? s : ''; };
                    // 结果容器（block-video- / cover-）内的播放器优先；页面常驻的推荐/banner
                    // 动效 video 不在结果容器里，兜底阶段才考虑，避免被误当成本片。
                    const inResult = v => {
                        let el = v;
                        for (let k = 0; k < 5 && el; k++) {
                            const cls = (el.className || '').toString();
                            if (cls.includes('block-video-') || cls.includes('cover-')) return true;
                            el = el.parentElement;
                        }
                        return false;
                    };
                    for (const v of vids) { if (inResult(v)) { const s = http(v); if (s) return s; } }
                    for (const v of vids) { const s = http(v); if (s) return s; }
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
            # 上游 _resolve_video_url 已优先换成无水印片源；这里不再改 lr 参数
            # （CDN 按路径 hash 锁片源，改 lr 转不出无水印）。
            clean_url = video_url
            logger.info("下载链: %s", video_url)
            # 留档：完整地址，便于排查水印
            try:
                out_dir = self.project_root / "output_videos"
                out_dir.mkdir(parents=True, exist_ok=True)
                with open(out_dir / "_captured_urls.json", "a") as f:
                    f.write(json.dumps({"ts": time.time(), "raw": video_url, "clean": clean_url}, ensure_ascii=False) + "\n")
            except Exception as e:
                logger.debug("下载直链落盘失败: %s", e)
            data = self._fetch_bytes(page, clean_url)
            if not data:
                logger.error("三种下载方式均失败: %s", video_url)
                return ""

            with open(save_path, "wb") as f:
                f.write(data)

            # 校验：MP4 头部
            ok = data[4:8] == b"ftyp" or b"ftyp" in data[:65536]
            codec = _detect_codec_fourcc(data)
            logger.info("视频已保存: %s (%.2f MB, MP4校验=%s, 编码=%s)",
                        save_path, len(data) / 1048576, ok, codec or "未知")
            if not ok:
                logger.warning("下载内容不像 MP4，可能是错误页")
            if codec in ("hev1", "hvc1", "hev2", "hvc2"):
                logger.warning("⚠ 该条为 H.265/HEVC(%s)，剪映可能报「格式异常」；"
                               "需换 H.264 片源或转码后再导入", codec)
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
            self.cost_samples.append((self._cost_key, cost))
            logger.info("本次单条消耗额度: %s（%s）", cost, self._cost_key)

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
        result = {"success": [], "failed": [], "total": len(tasks), "videos": {}, "reasons": {}}

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
                self.video_urls.clear()
                self.video_sources.clear()
                self.chain_vid = None
                self._wm_tried = False
                self._prompt_sent = False

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
                    self._use_task(task)
                    self.switch_to_video_mode(page, **self._mode_args(task))
                    self._push_status(shot_no, "video_mode", 30, "切换到视频生成模式")

                    images = self._task_files(task)
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
                        fail = self.last_fail or {"code": "UNKNOWN", "msg": "生成失败（未取得直链）", "conversation_url": ""}
                        result["reasons"][shot_no] = fail
                        self._push_status(shot_no, "failed", 0, fail["msg"])
                        if self._rejected(page):
                            logger.error("分镜 %s 被拒绝（版权/违规/风控），跳过本条", shot_no)
                        # 额度耗尽就整批停止，别再试后面的
                        elif self._quota_blocked(page):
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
        page_pairs: list = []  # (browser_page, task) 显式配对，避免发送失败后索引错位

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
            self._use_task(active_tasks[0])
            self.switch_to_video_mode(first_page, **self._mode_args(active_tasks[0]))

            # --- Tab1: 初始化 + 传图 + 发提示词（快速，不等确认）---
            t0 = active_tasks[0]
            imgs0 = self._task_files(t0)
            if imgs0:
                self.upload_images(first_page, imgs0)
            self._send_prompt_fast(first_page, t0.get("prompt", ""))
            logger.info("分镜 %s 已发送 (tab1)", t0.get("shot_no"))
            self._push_status(t0.get("shot_no"), "send_prompt", 50, "已发送提示词")
            page_pairs.append((first_page, t0))

            # --- Tab2..N: 快速开标签页 + 切视频模式 + 传图 + 发提示词 ---
            for i, task in enumerate(active_tasks[1:], start=1):
                try:
                    pg = context.new_page()
                    pg.set_default_timeout(30000)
                    pg.goto("https://www.doubao.com/chat/")
                    self._wait_js(pg, "() => !!document.querySelector('[contenteditable=true]')", 8000)
                    self.switch_to_video_mode(pg, **self._mode_args(task))
                    imgs = self._task_files(task)
                    if imgs:
                        self.upload_images(pg, imgs)
                    self._send_prompt_fast(pg, task.get("prompt", ""))
                    logger.info("分镜 %s 已发送 (tab%d)", task.get("shot_no"), i+1)
                    self._push_status(task.get("shot_no"), "send_prompt", 50, "已发送提示词")
                    page_pairs.append((pg, task))
                except Exception as e:
                    logger.error("分镜 %s 发送失败: %s", task.get("shot_no"), e)
                    result["failed"].append(task.get("shot_no"))
                    self._push_status(task.get("shot_no"), "failed", 0, "发送失败")

            # --- 快速轮询处理所有 tab 的确认 ---
            logger.info("全部 %d 条已发送，处理确认...", len(active_tasks))
            for t in active_tasks:
                self._push_status(t.get("shot_no"), "confirm", 55, "等待确认/渲染")
            for _ in range(20):
                time.sleep(3)
                any_confirm = False
                for pg, _task in page_pairs:
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
            rejected = set()  # 已被版权/风控拒绝的 shot_no（终态，不再轮询、不再补发确认）
            deadline = time.time() + 1200

            def _pending_tasks() -> list:
                return [t for t in active_tasks
                        if t.get("shot_no") not in done and t.get("shot_no") not in result["failed"]]

            while _pending_tasks() and time.time() < deadline:
                for pg, task in page_pairs:
                    shot_no = task.get("shot_no")
                    if shot_no in done or shot_no in rejected:
                        continue
                    try:
                        # 先判风控拒绝：命中即终态，不再处理确认、不再重复判定
                        if self._rejected(pg):
                            logger.error("分镜 %s 被拒绝（版权/违规/风控），跳过本条", shot_no)
                            rejected.add(shot_no)
                            if shot_no not in result["failed"]:
                                result["failed"].append(shot_no)
                            self._push_status(shot_no, "failed", 0, "内容被拒绝")
                            continue
                        self._handle_confirm_for(pg)
                        # 先确认本次结果已挂载，再读播放器链；结果未就绪时不读页面常驻的动效 video
                        if not self._result_ready(pg):
                            continue
                        # 取链口径对齐串行：先走等待窗口优先无水印接口片源、vid 主动换链，
                        # DOM 播放器预览流仅作兜底；直读旧逻辑会下载到带水印片源
                        src = self._wait_clean_url(pg, 5)
                        if not src:
                            dom = self._read_video_src(pg)
                            if dom and "vdl.doubao.com" in dom:
                                self._remember_video(dom, "dom")
                                src = dom
                        if src and "vdl.doubao.com" in src:
                            logger.info("分镜 %s 抓到直链，立即下载", shot_no)
                            self._push_status(shot_no, "got_url", 80, "提取视频URL")
                            vp, frame = self.download_video(pg, src, shot_no)
                            if vp:
                                done[shot_no] = vp
                                result["success"].append(shot_no)
                                result["videos"][shot_no] = vp
                                self._push_status(shot_no, "done", 100, "生成完成")
                                if on_video_ready:
                                    try:
                                        on_video_ready(task.get("shot_id"), shot_no, vp, frame)
                                    except Exception as cb_err:
                                        logger.error("回调写库失败: %r", cb_err, exc_info=True)
                                self._push_status(shot_no, "done", 100, "生成完成")
                            continue
                        boxes = self._candidate_covers(pg)
                        if boxes:
                            self._click_first_cover(pg, boxes)
                    except Exception as e:
                        logger.debug("分镜 %s 轮询异常: %s", shot_no, e)
                time.sleep(5)

            for _pg, task in page_pairs:
                shot_no = task.get("shot_no")
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
                for _ in range(10):
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
                try:
                    logger.info("=== 发送分镜 %s ===", shot_no)
                    self.new_conversation(page)
                    self.switch_to_video_mode(page, **self._mode_args(task))
                    images = self._task_files(task)
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
