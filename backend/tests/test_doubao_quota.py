"""豆包会员额度：解析（千分位、缺字段、code≠0）、监听读取、可用性（会员 / 非会员 / 读取失败）、成本中位数、批量分配。

纯单元测试：不开浏览器、不访问豆包，账号池用内存里的假集合。
"""
import copy
from datetime import date

import pytest

from core import doubao_quota as dq
from core.doubao_account_pool import DoubaoAccountPool
from core.providers import fake


@pytest.fixture(autouse=True)
def real_mode(monkeypatch):
    monkeypatch.delenv("DONGAI_FAKE_PROVIDERS", raising=False)


def _summary(total="16,100", used="0", exhausted=False, code=0, member=True, plan="标准套餐"):
    return {
        "code": code,
        "msg": "" if code == 0 else "not login",
        "data": {
            "current_subscription": {"display": {"short_name": plan}, "subscription_id": "secret-id", "price": 68},
            "member_info": {"hasActiveSubscription": member},
            "window_limit_section": {
                "entitlement_count": 2,
                "usage_exhausted": exhausted,
                "window_limit_groups": [{
                    "feature_group": "general",
                    "window_limits": [{"total_amount": total, "used_amount": used, "used_percent": 0,
                                       "window_type": 2, "start_time": 0, "end_time": 0, "item_type": 0}],
                }],
            },
        },
    }


# ------------------------------------------------------------------ 解析
@pytest.mark.parametrize("raw,expected", [
    ("16,100", 16100), ("1,234.5", 1234.5), (" 3 ", 3), (16100, 16100), (12.0, 12),
    ("", None), (None, None), ("abc", None), (True, None),
])
def test_parse_amount(raw, expected):
    assert dq.parse_amount(raw) == expected


def test_normalize_member_with_thousands_separator():
    q = dq.normalize_quota(_summary(total="16,100", used="1,250"), {"code": 0, "data": {"available_count": 3}})
    assert q["ok"] is True and q["is_member"] is True and q["plan_name"] == "标准套餐"
    assert q["total"] == 16100 and q["used"] == 1250 and q["exhausted"] is False
    assert q["window_type"] == 2 and q["reset_cards"] == 3 and q["error"] is None
    assert q["used_percent"] == 0
    # 只保留规范化字段，不带订阅 id、价格等原始字段
    assert set(q) == {"ok", "plan_name", "is_member", "total", "used", "used_percent", "exhausted",
                      "window_type", "reset_cards", "error", "fetched_at"}


def test_normalize_exhausted_by_flag_or_numbers():
    assert dq.normalize_quota(_summary(exhausted=True))["exhausted"] is True
    assert dq.normalize_quota(_summary(total="100", used="100"))["exhausted"] is True


def test_normalize_code_not_zero():
    q = dq.normalize_quota(_summary(code=10001))
    assert q["ok"] is False and "10001" in q["error"] and q["total"] is None


@pytest.mark.parametrize("resp", [None, "oops", {"code": 0}, {"code": 0, "data": None}, {"code": 0, "data": {}}])
def test_normalize_missing_fields(resp):
    q = dq.normalize_quota(resp)
    assert q["ok"] is False and q["error"]
    assert q["is_member"] is False


def test_normalize_missing_window_keeps_member_flag_but_not_ok():
    s = _summary()
    s["data"].pop("window_limit_section")
    q = dq.normalize_quota(s)
    assert q["ok"] is False and q["is_member"] is True and q["plan_name"] == "标准套餐"


def test_normalize_falls_back_to_enterprise_section_and_missing_used():
    s = _summary()
    sec = s["data"].pop("window_limit_section")
    sec["window_limit_groups"][0]["window_limits"][0].pop("used_amount")
    s["data"]["enterprise_window_limit_section"] = sec
    q = dq.normalize_quota(s, {"code": 1})
    assert q["ok"] is True and q["used"] == 0 and q["total"] == 16100 and q["reset_cards"] is None


def test_fake_quota_fixed(monkeypatch):
    monkeypatch.setenv("DONGAI_FAKE_PROVIDERS", "1")
    q = dq.read_quota(page=None)
    assert q["ok"] and q["plan_name"] == "标准套餐" and q["total"] == 16100 and q["used"] == 0
    assert dq.QuotaWatcher().snapshot()["total"] == 16100


# ------------------------------------------------------------------ 监听读取
class _Resp:
    def __init__(self, url, data, status=200):
        self.url, self._data, self.status = url, data, status

    def json(self):
        return self._data


def test_watcher_collects_page_responses():
    w = dq.QuotaWatcher()
    assert w.snapshot()["ok"] is False
    w._on_response(_Resp("https://www.doubao.com/other/", {"x": 1}))
    w._on_response(_Resp(dq.QUOTA_URL + "?a_bogus=x", _summary(used="10"), status=500))
    assert w.seq == 0
    w._on_response(_Resp(dq.QUOTA_URL + "?aid=1", _summary(used="10")))
    w._on_response(_Resp(dq.CARD_URL + "?aid=1", {"code": 0, "data": {"available_count": 1}}))
    q = w.snapshot()
    assert w.seq == 1 and q["ok"] and q["used"] == 10 and q["reset_cards"] == 1


def test_cost_between():
    a = dq.normalize_quota(_summary(used="100"))
    b = dq.normalize_quota(_summary(used="160"))
    assert dq.cost_between(a, b) == 60
    assert dq.cost_between(b, a) is None                       # 差值≤0 不记
    assert dq.cost_between(a, a) is None
    assert dq.cost_between(a, dq.empty_quota("x")) is None      # 读取失败不记
    assert dq.cost_between(a, dq.normalize_quota(_summary(total="20,000", used="200"))) is None  # 窗口变了


# ------------------------------------------------------------------ 账号池（内存假集合）
class FakeCol:
    def __init__(self, docs):
        self.docs = docs

    def find(self, flt=None, proj=None):
        return [copy.deepcopy(d) for d in self.docs]

    def find_one(self, flt, proj=None):
        for d in self.docs:
            if d["id"] == flt.get("id"):
                return copy.deepcopy(d)
        return None

    def update_many(self, flt, update):
        today = flt["usage.date"]["$ne"]
        for d in self.docs:
            if (d.get("usage") or {}).get("date") != today:
                d.update(copy.deepcopy(update["$set"]))

    def update_one(self, flt, update, upsert=False):
        for d in self.docs:
            if d["id"] != flt["id"]:
                continue
            for k, v in update.get("$set", {}).items():
                d[k] = copy.deepcopy(v)
            for path, spec in update.get("$push", {}).items():
                top, key = path.split(".", 1)
                arr = d.setdefault(top, {}).setdefault(key, [])
                arr.extend(spec["$each"])
                keep = -spec["$slice"]
                if len(arr) > keep:
                    del arr[:-keep]


def _pool(docs):
    pool = object.__new__(DoubaoAccountPool)
    pool._client = None
    pool._col = FakeCol(docs)
    return pool


TODAY = str(date.today())


def _acc(acc_id, used_today=0, quota=None, costs=None, enabled=True, account_type="free"):
    d = {"id": acc_id, "name": acc_id, "enabled": enabled, "account_type": account_type,
         "cookies": [{"name": "sessionid", "value": "s"}],
         "usage": {"date": TODAY, "count": used_today}}
    if quota is not None:
        d["quota"] = quota
    if costs is not None:
        d["quota_costs"] = {dq.DEFAULT_COST_KEY: costs}
    return d


MEMBER = dq.normalize_quota(_summary(total="16,100", used="100"))
NON_MEMBER = dq.normalize_quota(_summary(member=False))
FAILED = dq.empty_quota("等待额度接口超时")


def test_member_with_cost_ignores_daily_limit():
    pool = _pool([])
    info = pool.remaining_info(_acc("a", used_today=7, quota=MEMBER, costs=[100, 300, 200], account_type="member"))
    assert info["limit_mode"] == "member" and info["cost"] == 200
    assert info["remaining"] == (16100 - 100) // 200 and info["available"] is True
    assert info["batch_cap"] == info["remaining"]


def test_member_without_cost_is_unknown_but_available():
    pool = _pool([])
    info = pool.remaining_info(_acc("a", used_today=9, quota=MEMBER, account_type="member"))
    assert info["limit_mode"] == "member" and info["remaining"] is None
    assert info["available"] is True and info["batch_cap"] == pool.BATCH_UNKNOWN_CAP


def test_member_exhausted_not_available():
    pool = _pool([])
    q = dq.normalize_quota(_summary(exhausted=True))
    info = pool.remaining_info(_acc("a", quota=q, costs=[50], account_type="member"))
    assert info["remaining"] == 0 and info["available"] is False and info["batch_cap"] == 0


@pytest.mark.parametrize("quota", [None, NON_MEMBER, FAILED], ids=["never-read", "non-member", "read-failed"])
def test_daily_limit_fallback(quota):
    pool = _pool([])
    fresh = pool.remaining_info(_acc("a", used_today=1, quota=quota))
    assert fresh["limit_mode"] == "daily" and fresh["remaining"] == pool.DAILY_LIMIT - 1 and fresh["available"]
    full = pool.remaining_info(_acc("a", used_today=pool.DAILY_LIMIT, quota=quota))
    assert full["remaining"] == 0 and full["available"] is False
    # 昨天的用量不算今天
    old = _acc("a", used_today=5, quota=quota)
    old["usage"]["date"] = "2000-01-01"
    assert pool.remaining_info(old)["remaining"] == pool.DAILY_LIMIT


def test_cost_estimate_median_and_pool_fallback():
    a = _acc("a", quota=MEMBER, costs=[100, 120, 1000])
    b = _acc("b", quota=MEMBER)
    assert DoubaoAccountPool.cost_estimate(a) == 120
    assert DoubaoAccountPool.cost_estimate(b) is None
    assert DoubaoAccountPool.cost_estimate(b, [a, b]) == 120   # 自己没有样本时用全部账号同分键样本
    assert DoubaoAccountPool.cost_estimate(_acc("c", costs=[100, 200])) == 150


def test_record_costs_keeps_last_n_and_skips_non_positive():
    docs = [_acc("a", quota=MEMBER)]
    pool = _pool(docs)
    pool.record_costs("a", [(dq.DEFAULT_COST_KEY, c) for c in range(1, 15)] + [(dq.DEFAULT_COST_KEY, 0)])
    assert docs[0]["quota_costs"][dq.DEFAULT_COST_KEY] == list(range(15 - dq.COST_SAMPLES_KEEP, 15))


def test_get_available_account_skips_exhausted_and_full():
    exhausted = dq.normalize_quota(_summary(exhausted=True))
    pool = _pool([_acc("full", used_today=2), _acc("gone", quota=exhausted, account_type="member"),
                  _acc("off", enabled=False), _acc("member", used_today=30, quota=MEMBER, account_type="member")])
    assert pool.get_available_account()["id"] == "member"


def test_allocate_tasks_mixed_accounts():
    docs = [
        _acc("daily", used_today=1),                                       # 非会员：剩 1
        _acc("gone", quota=dq.normalize_quota(_summary(exhausted=True)), account_type="member"),  # 额度用完：不分配
        _acc("member_unknown", used_today=4, quota=MEMBER, account_type="member"),            # 会员无成本数据：每批最多 5
        _acc("failed", quota=FAILED),                                       # 读取失败：按每日 2
        _acc("off", enabled=False, quota=MEMBER),                           # 停用：不分配
    ]
    pool = _pool(docs)
    assert pool.get_total_available_quota() == 1 + 5 + 2
    alloc = pool.allocate_tasks(20)
    assert [(a["account_id"], a["task_count"]) for a in alloc] == [("daily", 1), ("member_unknown", 5), ("failed", 2)]
    assert [i for a in alloc for i in a["task_indices"]] == list(range(8))
    # 分配后计入今日用量；非会员此时已满，会员不受每日限额影响
    assert pool.get_account_by_id("daily")["usage"]["count"] == 2
    assert pool.remaining_info(pool.get_account_by_id("daily"))["available"] is False
    assert pool.remaining_info(pool.get_account_by_id("member_unknown"))["available"] is True
    # 只要 3 条时按顺序取，不多分
    pool2 = _pool([_acc("m", quota=MEMBER, account_type="member"), _acc("d")])  # 88352a1 起会员只看手动 account_type
    assert [(a["account_id"], a["task_count"]) for a in pool2.allocate_tasks(3)] == [("m", 3)]


def test_allocate_tasks_with_cost_data():
    """有成本数据：会员按 floor((total-used)/成本) 分；没样本的会员借用其它账号同分键的样本"""
    docs = [
        _acc("known", quota=dq.normalize_quota(_summary(total="1,000", used="400")), costs=[200, 150, 250], account_type="member"),  # 剩 3
        _acc("borrow", quota=dq.normalize_quota(_summary(total="1,000", used="0")), account_type="member"),                         # 借 200 → 5
        _acc("d"),
    ]
    pool = _pool(docs)
    assert pool.get_total_available_quota() == 3 + 5 + 2
    alloc = pool.allocate_tasks(9)
    assert [(a["account_id"], a["task_count"]) for a in alloc] == [("known", 3), ("borrow", 5), ("d", 1)]


def test_status_and_public_view_hide_cookies():
    docs = [_acc("m", quota=MEMBER, costs=[100], account_type="member"), _acc("d", used_today=1, quota=FAILED)]
    pool = _pool(docs)
    status = {s["id"]: s for s in pool.get_account_status()}
    assert status["m"]["limit_mode"] == "member" and status["m"]["remaining_estimate"] == 160
    assert status["m"]["quota"]["plan_name"] == "标准套餐"
    assert status["d"]["limit_mode"] == "daily" and status["d"]["remaining_estimate"] == 1
    assert all("cookies" not in s for s in status.values())
    view = pool.public_view(docs[0], docs)
    assert "cookies" not in view and "quota_costs" not in view
    assert view["remaining_estimate"] == 160 and view["limit_mode"] == "member" and view["logged_in"] is False
    # 并行多账号求和：会员 m min(160,5)=5，非会员 d min(1,5)=1 → 6
    assert pool.parallel_max() == 6


def test_allocate_parallel_round_robin_and_small_quota_first():
    # 2 条 / 2 账号各剩 2：轮流各一条 → A[0] B[1]
    p1 = _pool([_acc("a"), _acc("b")])
    a1 = {g["account_id"]: g["task_indices"] for g in p1.allocate_parallel(2)}
    assert a1 == {"a": [0], "b": [1]}

    # 3 条 / 2 账号各剩 2：轮流 → A[0,2] B[1]，第三条回 A 再开标签页
    p2 = _pool([_acc("a"), _acc("b")])
    a2 = {g["account_id"]: g["task_indices"] for g in p2.allocate_parallel(3)}
    assert a2 == {"a": [0, 2], "b": [1]}

    # 2 条 / 3 账号额度 2/1/2：优先把只剩 1 的 b 用完，再分 a
    p3 = _pool([_acc("a"), _acc("b", used_today=1), _acc("c")])
    a3 = {g["account_id"]: g["task_indices"] for g in p3.allocate_parallel(2)}
    assert a3 == {"b": [0], "a": [1]}
