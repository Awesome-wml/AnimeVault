"""仓库接口。所有方法为 async；返回的文档都是普通 dict 的拷贝（不含 _id）。

audit_logs 仓库只有 insert / search，没有任何 update / delete。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


class DuplicateError(Exception):
    """唯一键冲突（lid、username）。"""


class LicenseRepo:
    async def insert(self, doc: Dict[str, Any]) -> Dict[str, Any]: raise NotImplementedError
    async def get(self, lid: str) -> Optional[Dict[str, Any]]: raise NotImplementedError

    async def update(self, lid: str, fields: Dict[str, Any],
                     expect_status: Optional[Tuple[str, ...]] = None) -> Optional[Dict[str, Any]]:
        """更新字段；expect_status 给定时仅当当前状态在其中才更新（原子条件更新）。
        不满足或不存在返回 None。"""
        raise NotImplementedError

    async def search(self, *, status: Optional[str] = None, email: Optional[str] = None,
                     lid: Optional[str] = None, skip: int = 0, limit: int = 20
                     ) -> Tuple[List[Dict[str, Any]], int]:
        """按 issued_at 倒序；email/lid 为不区分大小写的包含匹配。返回 (页内容, 总数)。"""
        raise NotImplementedError

    async def find_same_machine(self, components: List[str]) -> List[Dict[str, Any]]:
        """分量集合完全相同、且未吊销的授权。"""
        raise NotImplementedError

    async def list_due(self, now: int) -> List[Dict[str, Any]]:
        """status=active 且 expires_at <= now。"""
        raise NotImplementedError


class AdminRepo:
    async def insert(self, doc: Dict[str, Any]) -> Dict[str, Any]: raise NotImplementedError
    async def get(self, admin_id: str) -> Optional[Dict[str, Any]]: raise NotImplementedError
    async def get_by_username(self, username: str) -> Optional[Dict[str, Any]]: raise NotImplementedError
    async def update(self, admin_id: str, fields: Dict[str, Any]) -> Optional[Dict[str, Any]]: raise NotImplementedError
    async def list(self) -> List[Dict[str, Any]]: raise NotImplementedError
    async def count_enabled_super(self) -> int: raise NotImplementedError


class AuditRepo:
    """只增不改：没有 update / delete。"""
    async def insert(self, doc: Dict[str, Any]) -> None: raise NotImplementedError

    async def search(self, *, action: Optional[str] = None, admin_id: Optional[str] = None,
                     skip: int = 0, limit: int = 20) -> Tuple[List[Dict[str, Any]], int]:
        raise NotImplementedError


class EventRepo:
    async def insert(self, doc: Dict[str, Any]) -> None: raise NotImplementedError
    async def list_for(self, lid: str) -> List[Dict[str, Any]]: raise NotImplementedError


class KeyRepo:
    async def upsert(self, kid: str, public_key: str, status: str = "active") -> None: raise NotImplementedError
    async def list(self) -> List[Dict[str, Any]]: raise NotImplementedError


class DeviceRepo:
    """设备记录：一个授权下可有多台（dev_max）。did 是服务端生成的设备记录 ID。"""
    async def insert(self, doc: Dict[str, Any]) -> None: raise NotImplementedError
    async def list_for(self, lid: str) -> List[Dict[str, Any]]:
        """按 first_seen_at 升序。"""
        raise NotImplementedError
    async def update(self, lid: str, did: str, fields: Dict[str, Any]) -> Optional[Dict[str, Any]]: raise NotImplementedError


class LeaseRepo:
    """租约记录：每个 (lid, sid) 一条，续租只更新 expires_at。"""
    async def upsert(self, lid: str, sid: str, fields: Dict[str, Any]) -> None: raise NotImplementedError
    async def get(self, lid: str, sid: str) -> Optional[Dict[str, Any]]: raise NotImplementedError
    async def list_for(self, lid: str) -> List[Dict[str, Any]]: raise NotImplementedError
    async def revoke_others(self, lid: str, keep_sid: str) -> int:
        """把该授权下除 keep_sid 外的租约记录标记 revoked。"""
        raise NotImplementedError


@dataclass
class Repos:
    licenses: LicenseRepo
    admins: AdminRepo
    audit: AuditRepo
    events: EventRepo
    keys: KeyRepo
    devices: DeviceRepo = None  # type: ignore[assignment]
    leases: LeaseRepo = None  # type: ignore[assignment]

    async def ensure_ready(self) -> None:
        """建索引等初始化；内存实现为空操作。"""
        return None

    async def close(self) -> None:
        return None
