"""
豆包账号池管理（MongoDB 版）
账号配置存在 dongai.doubao_accounts 集合里，不再依赖本地 JSON。
"""
import threading
import json
import math
import statistics
from datetime import datetime, date
from pathlib import Path
from typing import List, Optional, Dict

from pymongo import MongoClient
from pymongo.collection import Collection

from config.settings import settings
from core.doubao_quota import COST_SAMPLES_KEEP, DEFAULT_COST_KEY


class DoubaoAccountPool:
    """豆包账号池管理器（MongoDB 持久化）"""

    DAILY_LIMIT = 2  # 非会员 / 额度读取失败时，每个账号每天生成限额
    BATCH_UNKNOWN_CAP = 5  # 会员但还不知道单条成本时，批量分配每账号每批最多几条
    PARALLEL_TABS = 5      # 并行模式一个账号最多同时开几个标签页

    # 账号计费类型（手动指定为准，见 remaining_info）：member=按套餐额度，free=每日限额
    ACCOUNT_TYPES = ("member", "free")

    # 决定是否登录的核心会话凭证（取这组里最早过期的作为有效期基准）
    CORE_COOKIE_NAMES = {
        "sessionid", "sessionid_ss", "sid_tt", "uid_tt", "uid_tt_ss",
        "passport_auth_status", "passport_auth_status_ss",
    }

    def __init__(self):
        self._client: Optional[MongoClient] = None
        self._col: Optional[Collection] = None
        self._connect()
        self._migrate_from_json_if_needed()
        self._ensure_account_types()

    # 每个请求都会 new 一个账号池；MongoClient 自带连接池且线程安全，按连接串复用一个，
    # 原来每次 new 一个从不关闭，连接和后台监控线程越积越多
    _clients: dict = {}
    _clients_lock = threading.Lock()

    @classmethod
    def _shared_client(cls, url: str) -> MongoClient:
        with cls._clients_lock:
            client = cls._clients.get(url)
            if client is None:
                client = cls._clients[url] = MongoClient(url)
            return client

    def _connect(self):
        self._client = self._shared_client(settings.MONGODB_URL)
        self._col = self._client[settings.MONGODB_DB_NAME]["doubao_accounts"]
        self._col.create_index("id", unique=True)

    @property
    def col(self) -> Collection:
        if self._col is None:
            self._connect()
        return self._col

    def _migrate_from_json_if_needed(self):
        """首次运行：如果 Mongo 里还没有账号，把老的 doubao_accounts.json 导进来。"""
        if self.col.count_documents({}) > 0:
            return
        from config import paths
        legacy = paths.doubao_accounts_json()
        if legacy.exists():
            try:
                with open(legacy, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                for acc in cfg.get("accounts", []):
                    self.col.update_one({"id": acc["id"]}, {"$set": acc}, upsert=True)
            except Exception:
                pass

    def _ensure_account_types(self):
        """老账号补 account_type：历史上由额度读数自动推断会员的记为 member，其余 free。"""
        for acc in self.col.find({"account_type": {"$exists": False}}):
            q = acc.get("quota") or {}
            t = "member" if q.get("is_member") else "free"
            self.col.update_one({"id": acc["id"]}, {"$set": {"account_type": t}})

    # ---------- 内部 ----------
    def _list(self) -> List[Dict]:
        return list(self.col.find({}, {"_id": 0}))

    def cookie_remaining_days(self, cookies: list) -> Optional[float]:
        """返回核心会话 cookie 的剩余天数（取最早过期者）；无 cookie 返回 None。"""
        if not cookies:
            return None
        now = datetime.now().timestamp()
        exps = []
        for ck in cookies:
            if ck.get("name") in self.CORE_COOKIE_NAMES:
                exp = ck.get("expires", -1)
                if exp and exp > 0:
                    exps.append(exp)
        if not exps:
            return None
        return round((min(exps) - now) / 86400, 1)

    @staticmethod
    def login_status(acc: Dict) -> str:
        """登录状态以「有 cookie 且上次检查成功」为准：
        logged_in（可用）| need_recheck（标记已登录但没有 cookie，或上次检查出错）| logged_out。"""
        last = acc.get("last_check") or {}
        if last and not last.get("ok"):
            return "need_recheck"
        if acc.get("logged_in"):
            return "logged_in" if acc.get("cookies") else "need_recheck"
        return "logged_out"

    def annotate(self, acc: Dict) -> Dict:
        """给账号记录附带上 cookie 剩余天数、登录状态字段（不回写数据库）。"""
        days = self.cookie_remaining_days(acc.get("cookies", []))
        acc["cookie_days"] = days
        acc["cookie_expired"] = days is not None and days <= 0
        acc["login_status"] = self.login_status(acc)
        acc["logged_in"] = acc["login_status"] == "logged_in"
        return acc

    def _reset_expired_counts(self):
        today = str(date.today())
        self.col.update_many(
            {"usage.date": {"$ne": today}},
            {"$set": {"usage": {"date": today, "count": 0}}},
        )

    # ---------- 对外接口（保持和原来一致） ----------
    @property
    def accounts(self) -> List[Dict]:
        return self._list()

    def get_available_account(self) -> Optional[Dict]:
        """第一个启用且还能生成的账号（会员按额度、非会员按每日限额，见 remaining_info）。"""
        self._reset_expired_counts()
        accounts = self._list()
        for acc in accounts:
            if acc.get("enabled", True) and self.remaining_info(acc, accounts)["available"]:
                return acc
        return None

    def get_account_by_id(self, account_id: str) -> Optional[Dict]:
        acc = self.col.find_one({"id": account_id}, {"_id": 0})
        return acc

    def increment_usage(self, account_id: str) -> bool:
        today = str(date.today())
        acc = self.col.find_one({"id": account_id})
        if not acc:
            return False
        usage = acc.get("usage", {})
        if usage.get("date") != today:
            usage = {"date": today, "count": 0}
        usage["count"] = usage.get("count", 0) + 1
        self.col.update_one({"id": account_id}, {"$set": {"usage": usage}})
        return True

    def get_account_status(self) -> List[Dict]:
        self._reset_expired_counts()
        accounts = self._list()
        out = []
        for acc in accounts:
            info = self.remaining_info(acc, accounts)
            enabled = acc.get("enabled", True)
            days = self.cookie_remaining_days(acc.get("cookies", []))
            out.append({
                "id": acc["id"],
                "name": acc["name"],
                "enabled": enabled,
                "account_type": acc.get("account_type", "free"),
                "logged_in": self.login_status(acc) == "logged_in",
                "login_status": self.login_status(acc),
                "today_used": info["today_used"],
                "daily_limit": self.DAILY_LIMIT,
                "available": enabled and info["available"],
                "remaining": info["batch_cap"] if enabled else 0,
                **self.quota_fields(info),
                "quota": acc.get("quota") or None,
                "proxy": acc.get("proxy") or None,
                "cookie_days": days,
                "cookie_expired": days is not None and days <= 0,
            })
        return out

    def add_account(self, account: Dict) -> Dict:
        self.col.update_one({"id": account["id"]}, {"$set": account}, upsert=True)
        return account

    def update_account(self, account_id: str, patch: Dict) -> bool:
        res = self.col.update_one({"id": account_id}, {"$set": patch})
        return res.modified_count > 0 or res.matched_count > 0

    def delete_account(self, account_id: str):
        self.col.delete_one({"id": account_id})

    def rename_account(self, account_id: str, new_name: str):
        self.col.update_one({"id": account_id}, {"$set": {"name": new_name}})

    def set_account_type(self, account_id: str, account_type: str) -> bool:
        """切换计费类型（member/free）。转 free 时清掉套餐窗口残留字段，避免脏额度口径误导。"""
        if account_type not in self.ACCOUNT_TYPES:
            raise ValueError(f"未知账号类型: {account_type}")
        patch: Dict[str, object] = {"account_type": account_type}
        if account_type == "free":
            patch.update({
                "quota.total": None, "quota.used": None, "quota.used_percent": None,
                "quota.exhausted": None, "quota.window_type": None, "quota.is_member": False,
            })
        res = self.col.update_one({"id": account_id}, {"$set": patch})
        return res.matched_count > 0

    def set_login_state(self, account_id: str, logged_in: bool):
        self.col.update_one({"id": account_id}, {"$set": {"logged_in": logged_in}})

    def set_cookies(self, account_id: str, cookies: list):
        """把登录 cookie 列表持久化到数据库（替代本地 Profile 目录）"""
        self.col.update_one(
            {"id": account_id},
            {"$set": {"cookies": cookies or [], "logged_in": True}}
        )

    def record_check(self, account_id: str, ok: bool, error: Optional[str] = None):
        """记录最近一次登录检查：ok=False 表示检查本身出错（超时、目录被占用等），状态不可信。"""
        self.col.update_one(
            {"id": account_id},
            {"$set": {"last_check": {"at": datetime.now().isoformat(timespec="seconds"), "ok": ok, "error": error}}},
        )

    # ---------- 会员额度 ----------
    def set_quota(self, account_id: str, quota: Optional[Dict]):
        """保存规范化后的额度读数（core.doubao_quota.normalize_quota 的输出）。"""
        if quota:
            self.col.update_one({"id": account_id}, {"$set": {"quota": quota}})

    def record_costs(self, account_id: str, samples: List) -> None:
        """记录单条生成消耗的额度：samples=[(成本分键, 消耗)]，每个分键只留最近 COST_SAMPLES_KEEP 次。"""
        for key, cost in samples or []:
            if cost is None or cost <= 0:
                continue
            self.col.update_one(
                {"id": account_id},
                {"$push": {f"quota_costs.{key}": {"$each": [cost], "$slice": -COST_SAMPLES_KEEP}}},
            )

    def save_generation_quota(self, account_id: str, generator) -> None:
        """生成结束后把生成器读到的最新额度和本次成本样本写回账号。"""
        try:
            self.set_quota(account_id, getattr(generator, "last_quota", None))
            self.record_costs(account_id, getattr(generator, "cost_samples", None))
        except Exception:
            pass

    @staticmethod
    def cost_estimate(acc: Dict, accounts: Optional[List[Dict]] = None, key: str = DEFAULT_COST_KEY) -> Optional[float]:
        """单条成本估算：取该账号该分键最近样本的中位数；账号自己没有样本时用全部账号同分键样本。"""
        own = ((acc.get("quota_costs") or {}).get(key)) or []
        samples = [c for c in own if isinstance(c, (int, float)) and c > 0]
        if not samples and accounts:
            for other in accounts:
                samples += [c for c in ((other.get("quota_costs") or {}).get(key) or [])
                            if isinstance(c, (int, float)) and c > 0]
        return statistics.median(samples) if samples else None

    @staticmethod
    def is_member_mode(acc: Dict) -> bool:
        """计费类型以手动指定的 account_type 为准（member=套餐额度，free=每日限额）。"""
        return acc.get("account_type") == "member"

    def today_used(self, acc: Dict) -> int:
        usage = acc.get("usage") or {}
        return int(usage.get("count", 0) or 0) if usage.get("date") == str(date.today()) else 0

    def remaining_info(self, acc: Dict, accounts: Optional[List[Dict]] = None) -> Dict:
        """「剩余可生成条数」的唯一判断处（不看启用开关，调用方自己过滤）。

        - member（手动标为额度会员）：以 exhausted 为准；有成本数据时 remaining=floor((total-used)/成本)，
          没有成本数据时 remaining=None（未知但可用），批量分配每批最多 BATCH_UNKNOWN_CAP 条；
        - free / 额度读取失败 / 从未读取：remaining = DAILY_LIMIT - 今日用量。
        返回 {limit_mode, remaining, available, batch_cap, cost, today_used}。
        """
        used_today = self.today_used(acc)
        if self.is_member_mode(acc):
            q = acc.get("quota") or {}
            cost = self.cost_estimate(acc, accounts)
            total, used = q.get("total"), q.get("used") or 0
            if q.get("exhausted"):
                remaining = 0
            elif cost and total is not None:
                remaining = max(0, int(math.floor((total - used) / cost)))
            else:
                remaining = None
            available = remaining is None or remaining > 0
            batch_cap = self.BATCH_UNKNOWN_CAP if remaining is None else remaining
            return {"limit_mode": "member", "remaining": remaining, "available": available,
                    "batch_cap": batch_cap, "cost": cost, "today_used": used_today}
        remaining = max(0, self.DAILY_LIMIT - used_today)
        return {"limit_mode": "daily", "remaining": remaining, "available": remaining > 0,
                "batch_cap": remaining, "cost": None, "today_used": used_today}

    @staticmethod
    def quota_fields(info: Dict) -> Dict:
        """接口里附带的额度字段（quota 由调用方另行附上规范化读数）。"""
        return {"limit_mode": info["limit_mode"], "remaining_estimate": info["remaining"],
                "cost_estimate": info["cost"]}

    def public_view(self, acc: Dict, accounts: Optional[List[Dict]] = None) -> Dict:
        """给前端的账号记录：附带登录状态、额度摘要，去掉 cookie 原文和成本样本。"""
        out = self.annotate(dict(acc))
        out.pop("cookies", None)
        out.pop("quota_costs", None)
        info = self.remaining_info(acc, accounts)
        out.update(self.quota_fields(info))
        out["today_used"] = info["today_used"]
        out["quota"] = acc.get("quota") or None
        out["proxy"] = acc.get("proxy") or None
        return out

    # ---------- 分配 ----------
    def allocate_tasks(self, task_count: int) -> List[Dict]:
        """按账号顺序分配：每个账号最多分 batch_cap 条（会员已知成本=剩余条数，未知成本=BATCH_UNKNOWN_CAP，
        非会员=今日剩余），额度用完的账号不分配。分配后计入今日用量。"""
        self._reset_expired_counts()
        accounts = self._list()
        allocation = []
        idx = 0
        for acc in accounts:
            if idx >= task_count:
                break
            if not acc.get("enabled", True):
                continue
            info = self.remaining_info(acc, accounts)
            if not info["available"] or info["batch_cap"] <= 0:
                continue
            n = min(info["batch_cap"], task_count - idx)
            allocation.append({
                "account_id": acc["id"],
                "account_name": acc["name"],
                "profile_dir": acc.get("profile_dir", ""),
                "cookies": acc.get("cookies", []),
                "proxy": acc.get("proxy"),
                "task_indices": list(range(idx, idx + n)),
                "task_count": n,
            })
            for _ in range(n):
                self.increment_usage(acc["id"])
            idx += n
        return allocation

    def allocate_parallel(self, task_count: int) -> List[Dict]:
        """并行多账号分摊：逐条任务挑账号。

        选择规则：先均衡（已分到该账号的条数少优先）；条数相同时剩余额度少的优先
        （先把小额度账号用完）；单账号不超过 batch_cap 和 PARALLEL_TABS。
        分配时不扣今日用量，成功回调里再 increment_usage。
        返回 [{account_id, account_name, profile_dir, cookies, task_indices, task_count}]。
        """
        self._reset_expired_counts()
        accounts = self._list()
        cands = []
        for i, acc in enumerate(accounts):
            if not acc.get("enabled", True):
                continue
            info = self.remaining_info(acc, accounts)
            if not info["available"] or info["batch_cap"] <= 0:
                continue
            cands.append({"acc": acc, "cap": info["batch_cap"], "used": 0, "order": i})

        groups: Dict[str, Dict] = {}
        for idx in range(task_count):
            elig = [c for c in cands if c["used"] < min(c["cap"], self.PARALLEL_TABS)]
            if not elig:
                break
            # 已分配条数少 → 剩余额度少 → 账号顺序
            elig.sort(key=lambda c: (c["used"], c["cap"], c["order"]))
            pick = elig[0]
            pick["used"] += 1
            g = groups.get(pick["acc"]["id"])
            if g is None:
                g = {"account_id": pick["acc"]["id"], "account_name": pick["acc"]["name"],
                     "profile_dir": pick["acc"].get("profile_dir", ""),
                     "cookies": pick["acc"].get("cookies", []),
                     "proxy": pick["acc"].get("proxy"), "task_indices": []}
                groups[pick["acc"]["id"]] = g
            g["task_indices"].append(idx)
        return [dict(g, task_count=len(g["task_indices"])) for g in groups.values()]

    def parallel_max(self) -> int:
        """并行本批最多条数：各可用账号 min(剩余额度, 单账号标签页上限) 求和。"""
        self._reset_expired_counts()
        accounts = self._list()
        total = 0
        for acc in accounts:
            if not acc.get("enabled", True):
                continue
            info = self.remaining_info(acc, accounts)
            if info["available"]:
                total += min(info["batch_cap"], self.PARALLEL_TABS)
        return total

    def get_total_available_quota(self) -> int:
        """全部启用账号本批最多能分配的条数（未知成本的会员按 BATCH_UNKNOWN_CAP 计）。"""
        self._reset_expired_counts()
        accounts = self._list()
        return sum(self.remaining_info(a, accounts)["batch_cap"]
                   for a in accounts if a.get("enabled", True))
