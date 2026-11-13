"""
豆包会员额度读取与规范化。

登录后的豆包页面会请求两个接口：
- QUOTA_URL：订阅套餐与用量窗口（window_limit_section.window_limit_groups[].window_limits[]），
  数字是带千分位的字符串（"16,100"）；
- CARD_URL：额度重置卡数量（data.available_count）。

这些接口要带页面自己的登录态，所以在浏览器上下文里读：
监听页面自己发出的这两个请求的响应（打开 /chat/ 会自动请求）。页面内直接 fetch 实测返回 404
（缺页面 SDK 的签名参数与请求头），见 QuotaWatcher。

对外只输出规范化后的字段（见 empty_quota），不保存订阅 id、商户 id、价格、到期时间等原始字段。
替身模式（DONGAI_FAKE_PROVIDERS=1）下返回固定数据，不访问豆包。
"""
import logging
import re
import time
from datetime import datetime
from typing import Any, Dict, Optional

from core.providers import fake

logger = logging.getLogger(__name__)

QUOTA_URL = "https://www.doubao.com/alice/commerce/sale/subscription/quota/summary/"
CARD_URL = "https://www.doubao.com/alice/commerce/marketing/card/balance/"
QUOTA_PATH = "/alice/commerce/sale/subscription/quota/summary/"
CARD_PATH = "/alice/commerce/marketing/card/balance/"
CHAT_URL = "https://www.doubao.com/chat/"

# 当前视频生成固定用的模型与时长（core.doubao_automation.switch_to_video_mode），作为成本分键
VIDEO_MODEL = "Seedance 2.0 Fast"
VIDEO_DURATION = "15s"
COST_SAMPLES_KEEP = 10


def cost_key(model: str = VIDEO_MODEL, duration: str = VIDEO_DURATION) -> str:
    """成本分键：模型 + 时长。Mongo 字段名里不能有 '.'，统一换成 '_'。"""
    return f"{model}|{duration}".replace(".", "_")


DEFAULT_COST_KEY = cost_key()

def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def empty_quota(error: Optional[str] = None) -> Dict[str, Any]:
    return {
        "ok": False,
        "plan_name": None,
        "is_member": False,
        "total": None,
        "used": None,
        "used_percent": None,
        "exhausted": None,
        "window_type": None,
        "reset_cards": None,
        "error": error,
        "fetched_at": now_iso(),
    }


def parse_amount(value) -> Optional[float]:
    """'16,100' / '1,234.5' / 16100 / '' / None → 数字或 None。整数值返回 int。"""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        num = float(value)
    else:
        s = re.sub(r"[,\s，]", "", str(value))
        if not s:
            return None
        try:
            num = float(s)
        except ValueError:
            return None
    return int(num) if num.is_integer() else num


def _dig(obj, *keys):
    for k in keys:
        if not isinstance(obj, dict):
            return None
        obj = obj.get(k)
    return obj


def _pick_window(section) -> Optional[Dict]:
    """取用量窗口：优先 feature_group=general，其次第一个有 total_amount 的窗口。"""
    if not isinstance(section, dict):
        return None
    groups = section.get("window_limit_groups") or []
    if not isinstance(groups, list):
        return None
    ordered = sorted((g for g in groups if isinstance(g, dict)),
                     key=lambda g: 0 if g.get("feature_group") == "general" else 1)
    for g in ordered:
        for w in g.get("window_limits") or []:
            if isinstance(w, dict) and parse_amount(w.get("total_amount")) is not None:
                return {"section": section, "window": w}
    return None


def normalize_quota(summary: Any, card: Any = None, error: Optional[str] = None) -> Dict[str, Any]:
    """把 quota/summary（及 card/balance）响应规范化。任何缺字段 / code≠0 都不抛异常。"""
    if error:
        return empty_quota(error)
    if not isinstance(summary, dict):
        return empty_quota("额度接口返回格式不对")
    code = summary.get("code")
    if code not in (0, "0", None):
        msg = summary.get("msg") or summary.get("message") or ""
        return empty_quota(f"额度接口返回 code={code}{(' ' + str(msg)[:60]) if msg else ''}")
    data = summary.get("data")
    if not isinstance(data, dict):
        return empty_quota("额度接口没有 data")

    q = empty_quota()
    q["plan_name"] = _dig(data, "current_subscription", "display", "short_name") or None
    _active_sub = bool(_dig(data, "member_info", "hasActiveSubscription"))
    # 免费/体验/试用/赠送档不算付费会员：这类档位 hasActiveSubscription 也可能为真，
    # 但应按非会员每日限额走，不拿套餐点数窗口判耗尽。
    _free_plan = bool(q["plan_name"]) and any(
        k in str(q["plan_name"]) for k in ("免费", "体验", "试用", "赠送")
    )
    q["is_member"] = _active_sub and not _free_plan

    picked = _pick_window(data.get("window_limit_section")) or _pick_window(data.get("enterprise_window_limit_section"))
    if picked is None:
        q["error"] = "额度接口没有用量窗口"
        q["reset_cards"] = _card_count(card)
        # 能确认是否会员，但没有用量数据：仍视为读取失败，按每日限额走
        return q
    w, section = picked["window"], picked["section"]
    total = parse_amount(w.get("total_amount"))
    used = parse_amount(w.get("used_amount"))
    if used is None:
        used = 0
    pct = parse_amount(w.get("used_percent"))
    if pct is None and total:
        pct = round(used * 100.0 / total, 2)
    exhausted = section.get("usage_exhausted")
    if not isinstance(exhausted, bool):
        exhausted = total is not None and used >= total
    elif total is not None and used >= total:
        exhausted = True
    q.update({
        "ok": True,
        "total": total,
        "used": used,
        "used_percent": pct,
        "exhausted": exhausted,
        "window_type": w.get("window_type"),
        "reset_cards": _card_count(card),
        "error": None,
    })
    return q


def _card_count(card) -> Optional[int]:
    if not isinstance(card, dict) or card.get("code") not in (0, "0", None):
        return None
    n = parse_amount(_dig(card, "data", "available_count"))
    return int(n) if n is not None else None


def fake_quota() -> Dict[str, Any]:
    """替身模式固定数据：标准套餐会员，16,100 额度未使用。"""
    return normalize_quota(fake.QUOTA_SUMMARY, fake.QUOTA_CARD)


# ------------------------------------------------------------------ 浏览器读取
class QuotaWatcher:
    """监听页面自己发出的额度请求，保留最近一次响应。

    实测（2026-11-08）：在页面里直接 fetch 这两个接口返回 404——它们要页面 SDK 生成的 a_bogus 等签名和请求头，
    重放页面自己的完整 URL 也不行；打开 /chat/ 时页面会自动请求这两个接口（每次加载 1~2 次），监听响应稳定可用。
    所以只要挂在 context/page 上，每次打开或重新加载 /chat/ 都会顺带拿到最新额度，不额外发请求。
    """

    def __init__(self):
        self.summary: Optional[dict] = None
        self.card: Optional[dict] = None
        self.seq = 0  # 收到 summary 的次数，用来判断「这次加载之后有没有新读数」

    def attach(self, target) -> "QuotaWatcher":
        target.on("response", self._on_response)
        return self

    def detach(self, target) -> None:
        try:
            target.remove_listener("response", self._on_response)
        except Exception:
            pass

    def _on_response(self, resp) -> None:
        try:
            url = resp.url
            if QUOTA_PATH in url:
                kind = "summary"
            elif CARD_PATH in url:
                kind = "card"
            else:
                return
            if resp.status != 200:
                return
            data = resp.json()
            if kind == "summary":
                self.summary = data
                self.seq += 1
            else:
                self.card = data
        except Exception:
            pass

    def snapshot(self) -> Dict[str, Any]:
        """当前最近一次读数（规范化）；还没收到过额度响应时 ok=False。"""
        if fake.enabled():
            return fake_quota()
        if self.summary is None:
            return empty_quota("页面没有请求额度接口")
        return normalize_quota(self.summary, self.card)

    def wait_new(self, page, since: int, timeout_ms: int = 15000) -> bool:
        """等 seq 超过 since（页面加载后发出的新额度响应），再稍等重置卡数量。"""
        end = time.time() + timeout_ms / 1000
        while self.seq <= since and time.time() < end:
            page.wait_for_timeout(300)
        if self.seq <= since:
            return False
        card_end = time.time() + 1.5
        while self.card is None and time.time() < card_end:
            page.wait_for_timeout(200)
        return True

    def refresh(self, page, timeout_ms: int = 20000) -> Dict[str, Any]:
        """打开 /chat/ 读一次最新额度；失败返回 ok=False，不抛异常。"""
        if fake.enabled():
            return fake_quota()
        if page is None:
            return empty_quota("没有可用的页面")
        since = self.seq
        try:
            page.goto(CHAT_URL, wait_until="domcontentloaded", timeout=timeout_ms)
            if not self.wait_new(page, since, timeout_ms):
                return empty_quota("等待额度接口超时")
        except Exception as e:
            logger.warning("读取额度失败: %s", type(e).__name__)
            return empty_quota(f"读取额度失败: {type(e).__name__}")
        return self.snapshot()


def read_quota(page, timeout_ms: int = 20000) -> Dict[str, Any]:
    """在已登录的豆包页面里读一次额度（会把页面导航到 /chat/）。"""
    if fake.enabled():
        return fake_quota()
    watcher = QuotaWatcher()
    if page is None:
        return empty_quota("没有可用的页面")
    watcher.attach(page)
    try:
        return watcher.refresh(page, timeout_ms)
    finally:
        watcher.detach(page)


def cost_between(before: Optional[Dict], after: Optional[Dict]) -> Optional[float]:
    """一次生成前后两次读数的 used 差值；任一读数无效、窗口变了或差值≤0 时返回 None（不记录）。"""
    if not (before and after and before.get("ok") and after.get("ok")):
        return None
    if before.get("total") != after.get("total") or before.get("window_type") != after.get("window_type"):
        return None
    b, a = before.get("used"), after.get("used")
    if b is None or a is None:
        return None
    diff = a - b
    return diff if diff > 0 else None
