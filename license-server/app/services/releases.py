"""版本管理（设计第 14 节）：发布记录的草稿 / 发布 / 撤回、客户端 /update 查询、激活与续租的强制升级拦截。

状态：draft -> published -> withdrawn（撤回为终态，要重新发就新建一条草稿）。
强制升级线 = 同一 channel+platform 下所有已发布版本的 min_supported 的最大值；低于它的客户端被要求升级。
"""
from __future__ import annotations

import re
import secrets
import time
from typing import Any, Dict, List, Optional
from urllib.parse import urlsplit

from ..errors import ApiError
from ..repo.base import DuplicateError, Repos
from . import semver
from .audit import Actor, AuditService
from .ratelimit import RateLimiter

CHANNELS = ("stable", "beta")
PLATFORMS = ("mac-arm64", "mac-x64", "win-x64")
STATUSES = ("draft", "published", "withdrawn")
UPDATE_IP_LIMIT = 120        # /update 每 IP 每分钟
MAX_NOTES = 5000
MAX_SIZE = 1 << 40
_SHA_RE = re.compile(r"^[0-9a-fA-F]{64}$")
EDITABLE = ("version", "channel", "platform", "notes", "url", "sha256", "size", "min_supported")


def release_view(r: Dict[str, Any]) -> Dict[str, Any]:
    out = {k: v for k, v in r.items() if k != "seq"}
    out.setdefault("created_by_username", None)
    return out


def _bad(code: str, msg: str) -> ApiError:
    return ApiError(422, code, msg)


def check_channel(v: Any) -> str:
    if v not in CHANNELS:
        raise _bad("CHANNEL_INVALID", "渠道只能是 stable / beta")
    return v


def check_platform(v: Any) -> str:
    if v not in PLATFORMS:
        raise _bad("PLATFORM_INVALID", "平台只能是 " + " / ".join(PLATFORMS))
    return v


def check_version(v: Any, code: str = "VERSION_INVALID") -> str:
    if not isinstance(v, str) or not semver.is_valid(v):
        raise _bad(code, "版本号格式应为 x.y.z，可带 -预发布 与 +构建信息")
    return v.strip()


def check_url(v: Any) -> str:
    v = v.strip() if isinstance(v, str) else ""
    try:
        u = urlsplit(v)
        host = u.hostname
        u.port  # noqa: B018  触发端口合法性检查
    except ValueError:
        u, host = None, None
    ok = (u is not None and len(v) <= 2048 and not u.username and not u.password and host
          and (u.scheme == "https" or (u.scheme == "http" and host == "127.0.0.1")))
    if not ok:
        raise _bad("URL_INVALID", "下载地址必须是 https 地址（开发环境允许 http://127.0.0.1）")
    return v


def check_sha256(v: Any) -> str:
    if not isinstance(v, str) or not _SHA_RE.match(v.strip()):
        raise _bad("SHA256_INVALID", "sha256 必须是 64 位十六进制")
    return v.strip().lower()


def check_size(v: Any) -> int:
    if isinstance(v, bool) or not isinstance(v, int) or not 1 <= v <= MAX_SIZE:
        raise _bad("SIZE_INVALID", "文件大小必须是正整数（字节）")
    return v


def force_line(published: List[Dict[str, Any]]) -> Optional[str]:
    """已发布记录里最大的 min_supported（按 semver 比较，忽略构建信息）；没有则 None。"""
    best = None
    for r in published:
        m = r.get("min_supported")
        if m and (best is None or semver.parse(m) > semver.parse(best)):
            best = m
    return best


class ReleaseService:
    def __init__(self, repos: Repos, audit: AuditService, clock=time.time):
        self.r, self.audit, self.clock = repos, audit, clock
        self.limiter = RateLimiter(clock)

    def now(self) -> int:
        return int(self.clock())

    # ---------- 校验 ----------
    def _validate(self, f: Dict[str, Any]) -> Dict[str, Any]:
        out = {
            "version": check_version(f.get("version")),
            "channel": check_channel(f.get("channel")),
            "platform": check_platform(f.get("platform")),
            "url": check_url(f.get("url")),
            "sha256": check_sha256(f.get("sha256")),
            "size": check_size(f.get("size")),
        }
        notes = f.get("notes")
        if notes is None:
            notes = ""
        if not isinstance(notes, str) or len(notes) > MAX_NOTES:
            raise _bad("NOTES_INVALID", f"更新说明必须是不超过 {MAX_NOTES} 字的纯文本")
        out["notes"] = notes.strip()
        ms = f.get("min_supported")
        if ms is not None and ms != "":
            ms = check_version(ms, "MIN_SUPPORTED_INVALID")
            if semver.compare(ms, out["version"]) > 0:
                raise _bad("MIN_SUPPORTED_TOO_HIGH", "强制升级线不能高于该版本自身的版本号")
        else:
            ms = None
        out["min_supported"] = ms
        return out

    async def _check_dup(self, v: Dict[str, Any], skip_id: Optional[str] = None) -> None:
        """同 channel+platform 下版本号相同（忽略 +构建信息）也算重复。"""
        key = semver.parse(v["version"])
        for r in await self.r.releases.list_for(v["channel"], v["platform"]):
            if r["id"] != skip_id and semver.parse(r["version"]) == key:
                raise self._dup()

    @staticmethod
    def _dup() -> ApiError:
        return ApiError(409, "RELEASE_DUPLICATE", "该渠道和平台下已存在相同版本号")

    async def _get(self, rid: str) -> Dict[str, Any]:
        rel = await self.r.releases.get(rid)
        if rel is None:
            raise ApiError(404, "RELEASE_NOT_FOUND", "版本记录不存在")
        return rel

    @staticmethod
    def _snap(r: Dict[str, Any]) -> Dict[str, Any]:
        return {k: r.get(k) for k in ("version", "channel", "platform", "status", "url", "sha256", "size",
                                      "min_supported")}

    # ---------- 管理端 ----------
    async def create(self, actor: Actor, **fields) -> Dict[str, Any]:
        v = self._validate(fields)
        await self._check_dup(v)
        now = self.now()
        doc = {"id": "rel_" + secrets.token_hex(8), **v, "status": "draft", "created_at": now,
               "seq": time.time_ns(), "updated_at": now, "published_at": None, "withdrawn_at": None,
               "created_by": actor.admin_id, "created_by_username": actor.username}
        try:
            await self.r.releases.insert(doc)
        except DuplicateError:
            raise self._dup() from None
        await self.audit.record(actor, "release.create", f"release:{doc['id']}", None, self._snap(doc))
        return release_view(doc)

    async def update(self, actor: Actor, rid: str, changes: Dict[str, Any]) -> Dict[str, Any]:
        cur = await self._get(rid)
        if cur["status"] != "draft":
            raise ApiError(409, "RELEASE_NOT_DRAFT", "只有草稿可以修改", {"status": cur["status"]})
        v = self._validate({**{k: cur.get(k) for k in EDITABLE}, **changes})
        await self._check_dup(v, skip_id=rid)
        try:
            new = await self.r.releases.update(rid, {**v, "updated_at": self.now()}, expect_status=("draft",))
        except DuplicateError:
            raise self._dup() from None
        if new is None:  # 并发下刚被发布或撤回
            raise ApiError(409, "RELEASE_NOT_DRAFT", "只有草稿可以修改", {"status": (await self._get(rid))["status"]})
        await self.audit.record(actor, "release.update", f"release:{rid}", self._snap(cur), self._snap(new))
        return release_view(new)

    async def get(self, rid: str) -> Dict[str, Any]:
        return release_view(await self._get(rid))

    async def list(self, *, channel: Optional[str], platform: Optional[str], status: Optional[str],
                   page: int, page_size: int):
        if channel:
            check_channel(channel)
        if platform:
            check_platform(platform)
        if status and status not in STATUSES:
            raise _bad("STATUS_INVALID", "状态只能是 draft / published / withdrawn")
        items, total = await self.r.releases.search(channel=channel, platform=platform, status=status,
                                                    skip=(page - 1) * page_size, limit=page_size)
        return [release_view(i) for i in items], total

    async def _line(self, channel: str, platform: str) -> Optional[str]:
        return force_line(await self.r.releases.list_for(channel, platform, "published"))

    async def publish(self, actor: Actor, rid: str) -> Dict[str, Any]:
        cur = await self._get(rid)
        before = await self._line(cur["channel"], cur["platform"])
        new = await self.r.releases.update(rid, {"status": "published", "published_at": self.now(),
                                                 "updated_at": self.now()}, expect_status=("draft",))
        if new is None:
            raise ApiError(409, "INVALID_TRANSITION", f"当前状态为 {(await self._get(rid))['status']}，不能发布")
        after = await self._line(cur["channel"], cur["platform"])
        warnings = []
        if after != before:
            warnings.append(f"发布后强制升级线变为 {after}，低于该版本的 {cur['platform']}/{cur['channel']} 客户端将被要求升级")
        await self.audit.record(actor, "release.publish", f"release:{rid}", self._snap(cur), self._snap(new))
        return {"release": release_view(new), "warnings": warnings, "force_line": {"before": before, "after": after}}

    async def withdraw(self, actor: Actor, rid: str) -> Dict[str, Any]:
        cur = await self._get(rid)
        before = await self._line(cur["channel"], cur["platform"])
        new = await self.r.releases.update(rid, {"status": "withdrawn", "withdrawn_at": self.now(),
                                                 "updated_at": self.now()}, expect_status=("published",))
        if new is None:
            raise ApiError(409, "INVALID_TRANSITION", f"当前状态为 {(await self._get(rid))['status']}，只有已发布的版本可以撤回")
        after = await self._line(cur["channel"], cur["platform"])
        warnings = []
        if cur.get("min_supported") and after != before:
            warnings.append(f"该版本提供了强制升级线 {cur['min_supported']}，撤回后强制升级线变为 {after or '无'}")
        await self.audit.record(actor, "release.withdraw", f"release:{rid}", self._snap(cur), self._snap(new))
        return {"release": release_view(new), "warnings": warnings, "force_line": {"before": before, "after": after}}

    # ---------- 客户端 ----------
    async def check_update(self, version: str, platform: str, channel: str, ip: str) -> Dict[str, Any]:
        self.limiter.hit(f"upd-ip:{ip}", UPDATE_IP_LIMIT)
        cur = semver.parse(check_version(version))
        check_platform(platform)
        check_channel(channel)
        pub = await self.r.releases.list_for(channel, platform, "published")
        line = force_line(pub)
        latest = max(pub, key=lambda r: (semver.parse(r["version"]), r.get("published_at") or 0), default=None)
        available = latest is not None and semver.parse(latest["version"]) > cur
        return {"update_available": available,
                "latest": ({k: latest[k] for k in ("version", "notes", "url", "sha256", "size", "published_at")}
                           if latest else None),
                "force": line is not None and cur < semver.parse(line),
                "min_supported": line}

    async def enforce_min(self, app_version: Optional[str], platform: Optional[str],
                          channel: Optional[str]) -> None:
        """激活 / 续租前调用：app_version 低于强制升级线则抛 426。
        缺少 app_version / platform（老客户端）、或取值不认识时不拦截。channel 缺省按 stable。"""
        channel = channel or "stable"
        if not app_version or platform not in PLATFORMS or channel not in CHANNELS:
            return
        try:
            cur = semver.parse(app_version)
        except ValueError:
            return
        line = await self._line(channel, platform)
        if line is not None and cur < semver.parse(line):
            raise ApiError(426, "UPDATE_REQUIRED", f"当前版本过低，请升级到 {line} 或更高版本后再使用",
                           {"min_supported": line})
