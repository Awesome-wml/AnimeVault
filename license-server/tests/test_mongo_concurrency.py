"""Mongo 仓库并发检查：50 路并发激活/续租/踢下线/吊销，验证单会话、最后激活者胜出、吊销后续租必拒、唯一索引。

仅当 LS_MONGO_URL 存在且库名含 test 时运行（会清空该测试库）。每个用例都是可重复运行的。
"""
import asyncio
import dataclasses
import random
import time

import pytest

from app.config import DbSettings
from app.errors import ApiError
from app.repo.base import DuplicateError
from app.services import activation as act_mod
from app.services.activation import ActivationService
from app.services.audit import Actor, AuditService
from app.services.leases import LeaseService
from app.services.licenses import LicenseService
from tests.conftest import Clock, comps
from tests.test_mongo_integration import (MONGO_DB, MONGO_URL, clean_db,  # noqa: F401
                                          run_with_repos)
from dongai_license.machine_code import format_machine_code

pytestmark = pytest.mark.skipif(not (MONGO_URL and "test" in MONGO_DB.lower()),
                                reason="需要 LS_MONGO_URL 且库名含 test")

N = 50
IP = "10.0.0.1"
ADMIN = Actor(None, "ip")
MC = comps()


@pytest.fixture(autouse=True)
def no_rate_limit(monkeypatch):
    monkeypatch.setattr(act_mod, "ACTIVATE_IP_LIMIT", 10 ** 6)
    monkeypatch.setattr(act_mod, "ACTIVATE_LID_LIMIT", 10 ** 6)


class Env:
    def __init__(self, r, settings, clk):
        self.r = r
        self.licenses = LicenseService(r, settings, AuditService(r.audit), clk)
        self.leases = LeaseService(r, settings, self.licenses, clock=clk)
        self.act = ActivationService(self.leases)

    async def issue(self, dev_max=1):
        res = await self.licenses.issue(
            ADMIN, machine_code=format_machine_code(MC), plan="pro", features=["video"],
            expires_at=int(time.time()) + 86400 * 30, uid=None, email="u@e.com", dev_max=dev_max, note=None)
        return res["license"]

    async def activate(self, lic, c=None):
        return await self.act.activate(lic["code"], c or MC, "1.0", IP)

    async def renew(self, token, c=None):
        return await self.leases.renew(token, c or MC, "1.0", IP)


def sid_of(env, token):
    return env.leases.open_lease(token, MC)["sid"]


def with_env(settings, fn):
    s = dataclasses.replace(settings, db=DbSettings(store="mongo", mongo_url=MONGO_URL, mongo_db=MONGO_DB))
    clk = Clock()

    async def go(r):
        return await fn(Env(r, s, clk))

    async def go2(r):
        return await go(r)
    return run_with_repos(go2)


def err_code(x):
    return x.code if isinstance(x, ApiError) else None


def test_concurrent_activate_last_wins_single_session(settings):
    async def go(env):
        lic = await env.issue()
        res = await asyncio.gather(*[env.activate(lic) for _ in range(N)], return_exceptions=True)
        assert all(isinstance(x, dict) for x in res), [x for x in res if not isinstance(x, dict)]
        final = (await env.r.licenses.get(lic["lid"]))["active_sid"]
        sids = {sid_of(env, x["lease"]) for x in res}
        assert len(sids) == N and final in sids           # 每次激活一个新会话，最终会话是其中之一
        renewed = await asyncio.gather(*[env.renew(x["lease"]) for x in res], return_exceptions=True)
        ok = [(x, t) for x, t in zip(renewed, res) if isinstance(x, dict)]
        assert len(ok) == 1 and sid_of(env, ok[0][1]["lease"]) == final   # 只有最后会话能续租
        assert all(err_code(x) == "LICENSE_SESSION_CONFLICT" for x in renewed if not isinstance(x, dict))
        # 同一设备并发激活只能绑定一条设备记录
        devs = [d for d in await env.r.devices.list_for(lic["lid"]) if d.get("bound", True)]
        assert len(devs) == 1, len(devs)
    with_env(settings, go)


def test_concurrent_activate_respects_dev_max(settings):
    """dev_max=1：50 路并发，来自两台（分量容差内都匹配授权）不同设备，最终只能绑定 1 台。"""
    async def go(env):
        lic = await env.issue(dev_max=1)
        other = list(MC[:2]) + ["ff00" + "cd" * 6]   # 与授权码命中 2 个分量，但不是同一台设备记录
        res = await asyncio.gather(*[env.activate(lic, MC if i % 2 else other) for i in range(N)],
                                   return_exceptions=True)
        assert all(isinstance(x, dict) or err_code(x) == "LICENSE_MACHINE_MISMATCH" for x in res), res
        devs = [d for d in await env.r.devices.list_for(lic["lid"]) if d.get("bound", True)]
        assert len(devs) <= 1, len(devs)
    with_env(settings, go)


def test_mixed_activate_renew_kick_converges(settings):
    async def go(env):
        lic = await env.issue()
        first = await env.activate(lic)
        rnd = random.Random(7)
        jobs = ([env.renew(first["lease"]) for _ in range(20)] + [env.activate(lic) for _ in range(20)]
                + [env.licenses.kick(ADMIN, lic["lid"]) for _ in range(10)])
        rnd.shuffle(jobs)
        res = await asyncio.gather(*jobs, return_exceptions=True)
        for x in res:  # 只允许这些业务错误，不允许 500 级异常（含 Mongo 重复键等）
            assert isinstance(x, dict) or err_code(x) in {"LICENSE_SESSION_CONFLICT", "NO_ACTIVE_SESSION"}, repr(x)
        cur = await env.r.licenses.get(lic["lid"])
        tokens = [x["lease"] for x in res if isinstance(x, dict) and "lease" in x] + [first["lease"]]
        renewed = await asyncio.gather(*[env.renew(t) for t in tokens], return_exceptions=True)
        winners = [t for t, x in zip(tokens, renewed) if isinstance(x, dict)]
        if cur["active_sid"] is None:      # 最后动作是踢下线：所有租约都不能续
            assert not winners
        else:
            assert [sid_of(env, t) for t in winners] == [cur["active_sid"]] * len(winners) and len(winners) == 1
    with_env(settings, go)


def test_revoke_then_renew_always_rejected(settings):
    async def go(env):
        lic = await env.issue()
        tok = (await env.activate(lic))["lease"]
        revoked = asyncio.Event()
        late = []

        async def renew_loop(i):
            out = None
            for _ in range(8):                  # 每路持续续租，吊销前后都有请求在途
                await asyncio.sleep(random.random() * 0.02)
                started_after = revoked.is_set()   # 吊销已完成后才发起的续租必须被拒
                try:
                    await env.renew(tok)
                    out = None
                except ApiError as e:
                    out = e.code
                if started_after:
                    late.append(out)
            return out

        async def revoke():
            await asyncio.sleep(0.02)
            await env.licenses.revoke(ADMIN, lic["lid"])
            revoked.set()

        res = await asyncio.gather(revoke(), *[renew_loop(i) for i in range(N)])
        assert late and all(c == "LICENSE_REVOKED" for c in late), late
        assert {c for c in res[1:]} == {"LICENSE_REVOKED"}
        for _ in range(5):
            with pytest.raises(ApiError) as ei:
                await env.renew(tok)
            assert ei.value.code == "LICENSE_REVOKED"
        with pytest.raises(ApiError) as ei:
            await env.activate(lic)
        assert ei.value.code == "LICENSE_REVOKED"
        assert (await env.r.licenses.get(lic["lid"]))["status"] == "revoked"
    with_env(settings, go)


def test_unique_indexes_under_concurrency(settings):
    async def go(env):
        r = env.r
        lic = await env.issue()
        # leases(lid, sid) 唯一：并发 upsert 同一会话只留一条
        await asyncio.gather(*[r.leases.upsert(lic["lid"], "sid-x", {"mc": MC, "expires_at": i, "revoked": False})
                               for i in range(N)])
        assert len([x for x in await r.leases.list_for(lic["lid"]) if x["sid"] == "sid-x"]) == 1
        # 授权 lid 唯一
        dup = dict(lic)
        res = await asyncio.gather(*[r.licenses.insert(dict(dup)) for _ in range(N)], return_exceptions=True)
        assert all(isinstance(x, DuplicateError) for x in res)
        # 待处理申请 dedup_key 部分唯一：并发只成功一条
        base = {"email": "a@b.c", "dedup_key": "k1", "status": "pending", "created_at": 1}
        res = await asyncio.gather(*[r.requests.insert({**base, "id": f"req{i}"}) for i in range(N)],
                                   return_exceptions=True)
        assert sum(1 for x in res if isinstance(x, DuplicateError)) == N - 1
    with_env(settings, go)


def test_bind_lock_mutual_exclusion_and_expiry(settings):
    async def go(env):
        d = env.r.devices
        assert await d.lock("L", "a", 100.0, 10)
        assert not await d.lock("L", "b", 105.0, 10)       # 未过期，别人拿不到
        await d.unlock("L", "b")                            # 非持有者释放无效
        assert not await d.lock("L", "b", 105.0, 10)
        assert await d.lock("L", "b", 111.0, 10)            # 过期后可接管
        await d.unlock("L", "b")
        assert await d.lock("L", "c", 112.0, 10)
        got = await asyncio.gather(*[d.lock("M", f"o{i}", 100.0, 10) for i in range(N)])
        assert sum(got) == 1                                # 50 路争同一把锁只有一个成功
    with_env(settings, go)
