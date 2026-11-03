"""
豆包账号池管理
维护多个豆包账号的使用状态和每日配额
"""
import json
import os
from datetime import datetime, date
from typing import List, Optional, Dict
from pathlib import Path


class DoubaoAccountPool:
    """豆包账号池管理器"""
    
    DAILY_LIMIT = 5  # 每个账号每天生成限额
    
    def __init__(self, pool_file: str = None):
        """
        初始化账号池
        
        Args:
            pool_file: 账号池配置文件路径
        """
        if pool_file is None:
            pool_file = Path(__file__).parent.parent.parent / "doubao_accounts.json"
        self.pool_file = Path(pool_file)
        self.accounts = []
        self._load_accounts()
    
    def _load_accounts(self):
        """加载账号配置"""
        if not self.pool_file.exists():
            # 创建默认配置
            default_config = {
                "accounts": [
                    {
                        "id": "account_1",
                        "name": "豆包账号1",
                        "profile_dir": ".doubao_profiles/account_1",
                        "enabled": True,
                        "usage": {
                            "date": str(date.today()),
                            "count": 0
                        }
                    }
                ],
                "notes": "profile_dir 是相对于项目根目录的 Chrome Profile 路径，每个账号需要独立登录一次"
            }
            self.pool_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.pool_file, 'w', encoding='utf-8') as f:
                json.dump(default_config, f, indent=2, ensure_ascii=False)
            self.accounts = default_config["accounts"]
        else:
            with open(self.pool_file, 'r', encoding='utf-8') as f:
                config = json.load(f)
                self.accounts = config.get("accounts", [])
        
        # 重置过期的计数
        self._reset_expired_counts()
    
    def _save_accounts(self):
        """保存账号配置"""
        config = {
            "accounts": self.accounts,
            "notes": "profile_dir 是相对于项目根目录的 Chrome Profile 路径，每个账号需要独立登录一次"
        }
        with open(self.pool_file, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
    
    def _reset_expired_counts(self):
        """重置过期日期的计数"""
        today = str(date.today())
        changed = False
        for account in self.accounts:
            usage = account.get("usage", {})
            if usage.get("date") != today:
                account["usage"] = {"date": today, "count": 0}
                changed = True
        if changed:
            self._save_accounts()
    
    def get_available_account(self) -> Optional[Dict]:
        """
        获取一个可用账号（计数 < 限额）
        
        Returns:
            可用账号信息，如果没有可用账号则返回 None
        """
        self._reset_expired_counts()
        
        for account in self.accounts:
            if not account.get("enabled", True):
                continue
            
            usage = account.get("usage", {})
            count = usage.get("count", 0)
            
            if count < self.DAILY_LIMIT:
                return account
        
        return None
    
    def get_account_by_id(self, account_id: str) -> Optional[Dict]:
        """根据 ID 获取账号"""
        for account in self.accounts:
            if account["id"] == account_id:
                return account
        return None
    
    def increment_usage(self, account_id: str) -> bool:
        """
        增加账号使用计数
        
        Args:
            account_id: 账号 ID
            
        Returns:
            是否成功
        """
        account = self.get_account_by_id(account_id)
        if not account:
            return False
        
        today = str(date.today())
        usage = account.get("usage", {})
        
        if usage.get("date") != today:
            usage = {"date": today, "count": 0}
        
        usage["count"] += 1
        account["usage"] = usage
        self._save_accounts()
        return True
    
    def get_account_status(self) -> List[Dict]:
        """
        获取所有账号状态
        
        Returns:
            账号状态列表
        """
        self._reset_expired_counts()
        
        status_list = []
        for account in self.accounts:
            usage = account.get("usage", {})
            count = usage.get("count", 0)
            available = count < self.DAILY_LIMIT and account.get("enabled", True)
            
            status_list.append({
                "id": account["id"],
                "name": account["name"],
                "enabled": account.get("enabled", True),
                "today_used": count,
                "daily_limit": self.DAILY_LIMIT,
                "available": available,
                "remaining": max(0, self.DAILY_LIMIT - count) if available else 0
            })
        
        return status_list
    
    def allocate_tasks(self, task_count: int) -> List[Dict]:
        """
        分配任务到账号
        
        Args:
            task_count: 总任务数
            
        Returns:
            分配方案列表，每项包含 account_id 和 task_indices (任务索引列表)
        """
        self._reset_expired_counts()
        
        allocation = []
        current_task_index = 0
        
        while current_task_index < task_count:
            account = self.get_available_account()
            if not account:
                # 没有可用账号了
                break
            
            # 计算该账号可以处理多少任务
            usage = account.get("usage", {})
            used = usage.get("count", 0)
            remaining = self.DAILY_LIMIT - used
            
            # 分配任务
            tasks_to_assign = min(remaining, task_count - current_task_index)
            task_indices = list(range(current_task_index, current_task_index + tasks_to_assign))
            
            allocation.append({
                "account_id": account["id"],
                "account_name": account["name"],
                "profile_dir": account["profile_dir"],
                "task_indices": task_indices,
                "task_count": tasks_to_assign
            })
            
            # 更新使用计数
            for _ in range(tasks_to_assign):
                self.increment_usage(account["id"])
            
            current_task_index += tasks_to_assign
        
        return allocation
    
    def get_total_available_quota(self) -> int:
        """获取今天所有账号剩余的总配额"""
        self._reset_expired_counts()
        total = 0
        for account in self.accounts:
            if not account.get("enabled", True):
                continue
            usage = account.get("usage", {})
            count = usage.get("count", 0)
            total += max(0, self.DAILY_LIMIT - count)
        return total
