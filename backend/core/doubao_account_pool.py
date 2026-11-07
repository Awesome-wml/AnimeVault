"""
豆包账号池管理（MongoDB 版）
账号配置存在 dongai.doubao_accounts 集合里，不再依赖本地 JSON。
"""
import json
from datetime import datetime, date
from pathlib import Path
from typing import List, Optional, Dict

from pymongo import MongoClient
from pymongo.collection import Collection

from config.settings import settings


class DoubaoAccountPool:
    """豆包账号池管理器（MongoDB 持久化）"""

    DAILY_LIMIT = 2  # 每个账号每天生成限额

    def __init__(self):
        self._client: Optional[MongoClient] = None
        self._col: Optional[Collection] = None
        self._connect()
        self._migrate_from_json_if_needed()

    def _connect(self):
        self._client = MongoClient(settings.MONGODB_URL)
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
        legacy = Path(__file__).parent.parent.parent / "doubao_accounts.json"
        if legacy.exists():
            try:
                with open(legacy, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                for acc in cfg.get("accounts", []):
                    self.col.update_one({"id": acc["id"]}, {"$set": acc}, upsert=True)
            except Exception:
                pass

    # ---------- 内部 ----------
    def _list(self) -> List[Dict]:
        return list(self.col.find({}, {"_id": 0}))

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
        self._reset_expired_counts()
        today = str(date.today())
        cur = self.col.find(
            {"enabled": True, "usage.date": today, "usage.count": {"$lt": self.DAILY_LIMIT}}
        )
        for acc in cur:
            acc.pop("_id", None)
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
        today = str(date.today())
        out = []
        for acc in self.col.find({}, {"_id": 0}):
            usage = acc.get("usage", {})
            count = usage.get("count", 0)
            available = count < self.DAILY_LIMIT and acc.get("enabled", True)
            out.append({
                "id": acc["id"],
                "name": acc["name"],
                "enabled": acc.get("enabled", True),
                "logged_in": acc.get("logged_in", False),
                "today_used": count,
                "daily_limit": self.DAILY_LIMIT,
                "available": available,
                "remaining": max(0, self.DAILY_LIMIT - count) if available else 0,
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

    def set_login_state(self, account_id: str, logged_in: bool):
        self.col.update_one({"id": account_id}, {"$set": {"logged_in": logged_in}})

    def allocate_tasks(self, task_count: int) -> List[Dict]:
        self._reset_expired_counts()
        allocation = []
        idx = 0
        while idx < task_count:
            acc = self.get_available_account()
            if not acc:
                break
            used = acc.get("usage", {}).get("count", 0)
            remaining = self.DAILY_LIMIT - used
            n = min(remaining, task_count - idx)
            allocation.append({
                "account_id": acc["id"],
                "account_name": acc["name"],
                "profile_dir": acc["profile_dir"],
                "task_indices": list(range(idx, idx + n)),
                "task_count": n,
            })
            for _ in range(n):
                self.increment_usage(acc["id"])
            idx += n
        return allocation

    def get_total_available_quota(self) -> int:
        self._reset_expired_counts()
        today = str(date.today())
        total = 0
        for acc in self.col.find({"enabled": True, "usage.date": today}, {"usage.count": 1}):
            total += max(0, self.DAILY_LIMIT - acc.get("usage", {}).get("count", 0))
        return total
