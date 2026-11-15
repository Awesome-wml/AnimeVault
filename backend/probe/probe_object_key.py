"""
探针：验证豆包 web 上传参考图的 object_key 抓取与 attachment 标记方案。

目标（分步只读观察，不改业务代码、不回车发送、不触发生成）：
  stage=login  连接已登录会话，打开对话页，确认输入框与登录态；
  stage=upload 挂上传接口响应监听，上传一张测试图，抓返回包里的 object_key 候选；
  stage=dom    上传后读取输入框内 attachment 节点结构（img / data-* / 链接）。

用法（cwd=backend）：
  .venv-host/bin/python -m probe.probe_object_key --stage login
  .venv-host/bin/python -m probe.probe_object_key --stage upload
  .venv-host/bin/python -m probe.probe_object_key --stage dom
  .venv-host/bin/python -m probe.probe_object_key --stage upload --image ../static/images/prev_frame_shot5.png
"""
import argparse
import json
import logging
import time
from pathlib import Path
from typing import Optional

from playwright.sync_api import sync_playwright, Page, BrowserContext

from utils.file_util import FileUtil

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BACKEND_DIR.parent
PROFILE_DIR = PROJECT_ROOT / ".doubao_profiles" / "account_1"
CHAT_URL = "https://www.doubao.com/chat/"
DEBUG_PORT = 19301

# 只抓上传两步接口与二进制上传域；初始化/配置/额度等 /alice 接口一律不抓
UPLOAD_PATH_MARKS = ("resource/prepare_upload", "ApplyImageUpload")
UPLOAD_HOST_MARKS = ("snssdk.com", "tos-", "tos-cn", "imagex")
# 响应体里疑似资源标识的字段名关键词
KEY_FIELD_MARKS = ("key", "uri", "url", "token", "id", "hash", "path")


def _interested(url: str) -> bool:
    return any(m in url for m in UPLOAD_PATH_MARKS) or any(m in url for m in UPLOAD_HOST_MARKS)

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("probe")


def walk_keys(obj, path="") -> list:
    """递归收集疑似资源标识字段（字段名含 key/uri/url/token/id/hash/path，值为非空串）。"""
    out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            p = f"{path}.{k}" if path else k
            if isinstance(v, (dict, list)):
                out += walk_keys(v, p)
            elif isinstance(v, str) and v and any(m in k.lower() for m in KEY_FIELD_MARKS):
                out.append((p, v))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out += walk_keys(v, f"{path}[{i}]")
    return out


def load_account_cookies(account_id: str = "account_1") -> list:
    """从 Mongo 同步读账号 cookies（与业务 connect_with_cookies 同一套登录态来源）。"""
    from pymongo import MongoClient
    from config.settings import settings

    client = MongoClient(settings.MONGODB_URL)
    db = client[settings.MONGODB_DB_NAME]
    acc = db["doubao_accounts"].find_one({"id": account_id})
    return (acc.get("cookies") or []) if acc else []


def connect(pw):
    """launch 新 Chrome 无目录 context，注入账号 cookies（避开外部 CDP 握手的 setDownloadBehavior 兼容问题）。"""
    cookies = load_account_cookies()
    log.info("[connect] 读到 cookies %d 条", len(cookies))
    browser = pw.chromium.launch(
        channel="chrome",
        headless=False,
        args=["--disable-blink-features=AutomationControlled", "--disable-dev-shm-usage"],
    )
    ctx = browser.new_context(viewport={"width": 1280, "height": 800})
    if cookies:
        ctx.add_cookies(cookies)
    return ctx, "cookies", browser


def ensure_chat(page: Page) -> bool:
    page.goto(CHAT_URL, wait_until="domcontentloaded", timeout=30000)
    try:
        page.wait_for_selector('[contenteditable=true]', timeout=10000)
        return True
    except Exception:
        return False


def attach_upload_listener(ctx: BrowserContext, captured: list):
    def _on_response(resp):
        u = resp.url
        if not _interested(u):
            return
        try:
            ct = resp.headers.get("content-type", "")
            body = None
            if "json" in ct:
                try:
                    body = resp.json()
                except Exception:
                    try:
                        body = (resp.text() or "")[:800]
                    except Exception:
                        body = None
            captured.append({
                "method": resp.request.method,
                "status": resp.status,
                "url": u,
                "content_type": ct,
                "body": body,
            })
        except Exception:
            # 窗口/上下文关闭时读 body 会抛 CancelledError / TargetClosedError，静默忽略
            pass

    ctx.on("response", _on_response)


def pick_test_image(arg: Optional[str]) -> Path:
    if arg:
        p = Path(arg)
        if not p.is_absolute():
            p = BACKEND_DIR / p
        if p.exists():
            return p
        log.warning("指定图不存在，回退默认测试图: %s", p)
    images = FileUtil.get_images_dir()
    for cand in ("prev_frame_shot5.png", "prev_frame_shot4.png"):
        if (images / cand).exists():
            return images / cand
    raise SystemExit("static/images 下没有可用测试图，用 --image 指定一张")


def attachment_mark(store_uri: str, name: str = "") -> str:
    """拼豆包 attachment 标记：[alt](attachment://{StoreUri}?type=1)。StoreUri 动态，其余写死。"""
    return f"[{name}](attachment://{store_uri}?type=1)"


def _find_store_uri(obj, out: list):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "StoreUri" and isinstance(v, str):
                out.append(v)
            else:
                _find_store_uri(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _find_store_uri(v, out)


def extract_store_uri(captured: list) -> Optional[str]:
    for c in captured:
        body = c.get("body")
        if isinstance(body, dict):
            found: list = []
            _find_store_uri(body, found)
            if found:
                return found[0]
    return None


def stage_login(page: Page):
    ok = ensure_chat(page)
    log.info("[login] 输入框就绪: %s", ok)
    if not ok:
        log.info("[login] 可能未登录，页面标题: %s", page.title())
        return
    ed = page.query_selector('[contenteditable=true]')
    log.info("[login] contenteditable 节点: %s", bool(ed))


def stage_upload(page: Page, captured: list, image: Path):
    ensure_chat(page)
    log.info("[upload] 测试图: %s (%d 字节)", image.name, image.stat().st_size)
    file_input = page.query_selector('input[type=file]')
    if not file_input:
        log.error("[upload] 未找到 input[type=file]，先看页面是否在对话页/视频模式")
        return
    file_input.set_input_files(str(image))
    # 等上传缩略图出现（沿用自动化的判定：底部区域宽度>40 的 img）
    try:
        page.wait_for_function(
            """() => [...document.querySelectorAll('img')].some(im => {
                const r = im.getBoundingClientRect();
                return r.width > 40 && r.bottom > 600;
            })""",
            timeout=12000,
        )
        log.info("[upload] 缩略图已出现")
    except Exception:
        log.warning("[upload] 12s 内未观察到缩略图，继续打印已抓接口")
    time.sleep(1.5)

    log.info("[upload] 命中素材类接口 %d 条:", len(captured))
    for i, c in enumerate(captured):
        log.info("--- #%d %s %s status=%s ct=%s", i, c.get("method"), c["url"], c.get("status"), c.get("content_type"))
        body = c.get("body")
        if isinstance(body, dict) and ("prepare_upload" in c["url"] or "ApplyImageUpload" in c["url"]):
            log.info("    [完整 body] %s", json.dumps(body, ensure_ascii=False)[:2000])
        if body is None:
            continue
        if isinstance(body, (dict, list)):
            keys = walk_keys(body)
            if keys:
                for p, v in keys:
                    log.info("    %s = %s", p, v)
            else:
                log.info("    body=%s", json.dumps(body, ensure_ascii=False)[:400])
        else:
            log.info("    body=%s", str(body)[:400])

    # 同一轮观察草稿里的附件节点（新窗口不保留上一轮草稿）
    stage_dom(page)


def stage_mark(page: Page, captured: list, image: Path):
    """上传图拿 StoreUri → 拼 attachment 标记 → 插入输入框观察渲染（不发送）。"""
    ensure_chat(page)
    log.info("[mark] 测试图: %s (%d 字节)", image.name, image.stat().st_size)
    file_input = page.query_selector('input[type=file]')
    if not file_input:
        log.error("[mark] 未找到 input[type=file]")
        return
    file_input.set_input_files(str(image))
    try:
        page.wait_for_function(
            """() => [...document.querySelectorAll('img')].some(im => {
                const r = im.getBoundingClientRect();
                return r.width > 40 && r.bottom > 600;
            })""",
            timeout=12000,
        )
        log.info("[mark] 缩略图已出现")
    except Exception:
        log.warning("[mark] 未观察到缩略图")
    time.sleep(1.5)

    store_uri = extract_store_uri(captured)
    if not store_uri:
        log.error("[mark] 没抓到 StoreUri，无法拼标记")
        return
    mark = attachment_mark(store_uri, image.name)
    log.info("[mark] StoreUri = %s", store_uri)
    log.info("[mark] 拼接标记:\n%s", mark)


def stage_dom(page: Page):
    ensure_chat(page)
    ed = page.query_selector('[contenteditable=true]')
    if not ed:
        log.error("[dom] 没有输入框")
        return
    html = ed.inner_html() or ""
    log.info("[dom] 输入框 inner_html 长度=%d", len(html))
    # 列出输入框内所有 img 及其属性
    imgs = page.evaluate(
        """() => {
            const ed = document.querySelector('[contenteditable=true]');
            if (!ed) return [];
            return [...ed.querySelectorAll('img')].map(im => ({
                src: (im.src || '').slice(0, 160),
                dataset: {...im.dataset},
                alt: im.alt || '',
                cls: im.className || ''
            }));
        }"""
    )
    log.info("[dom] 输入框内 img %d 张:", len(imgs))
    for im in imgs:
        log.info("    %s", json.dumps(im, ensure_ascii=False))
    # 向上找输入容器，覆盖附件胶囊可能所在的外层节点
    nodes = page.evaluate(
        """() => {
            const ed = document.querySelector('[contenteditable=true]');
            if (!ed) return [];
            let box = ed;
            for (let i = 0; i < 5 && box.parentElement; i++) box = box.parentElement;
            const sel = 'img, a, [class*=attach], [class*=image], [class*=file], [class*=preview], [class*=card]';
            return [...box.querySelectorAll(sel)].slice(0, 30).map(n => ({
                tag: n.tagName,
                cls: n.className || '',
                dataset: {...n.dataset},
                hasData: Object.keys(n.dataset).length > 0,
                src: (n.src || '').slice(0, 160),
                href: n.href || '',
                text: (n.innerText || '').slice(0, 40),
                html: n.outerHTML.slice(0, 300)
            }));
        }"""
    )
    log.info("[dom] 附件/链接类节点 %d 个:", len(nodes))
    for n in nodes:
        log.info("    %s", json.dumps(n, ensure_ascii=False))
    log.info("[dom] inner_html 片段:\n%s", html[:1200])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", choices=["login", "upload", "dom", "mark"], default="login")
    ap.add_argument("--image", default=None, help="测试图路径（相对 backend 或绝对）")
    ap.add_argument("--keep-open", action="store_true", help="结束后保留窗口不退出")
    args = ap.parse_args()

    captured: list = []
    pw = sync_playwright().start()
    ctx: Optional[BrowserContext] = None
    browser = None
    try:
        ctx, mode, browser = connect(pw)
        log.info("[connect] 模式=%s profile=%s", mode, PROFILE_DIR)
        attach_upload_listener(ctx, captured)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.set_default_timeout(30000)

        if args.stage == "login":
            stage_login(page)
        elif args.stage == "upload":
            stage_upload(page, captured, pick_test_image(args.image))
        elif args.stage == "dom":
            stage_dom(page)
        elif args.stage == "mark":
            stage_mark(page, captured, pick_test_image(args.image))

        if args.keep_open:
            log.info("[keep-open] 窗口保留，回车退出...")
            input()
    finally:
        if args.keep_open:
            pass
        elif browser is not None:
            browser.close()
        elif ctx is not None:
            ctx.close()
        pw.stop()


if __name__ == "__main__":
    main()
