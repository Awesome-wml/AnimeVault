"""桌面模式强制禁用 Redis：不发起任何连接，忽略 REDIS_URL；非桌面模式行为不变。"""
import asyncio

import pytest

from db import redis_client
from db.redis_client import RedisClient


@pytest.fixture(autouse=True)
def _reset():
    RedisClient.client, RedisClient.enabled = None, False
    yield
    RedisClient.client, RedisClient.enabled = None, False


class _Boom:
    def __init__(self):
        self.calls = 0

    def from_url(self, *a, **k):
        self.calls += 1
        raise AssertionError("桌面模式不应创建 Redis 连接")


def test_desktop_never_connects(monkeypatch):
    monkeypatch.setenv("DONGAI_DESKTOP", "1")
    monkeypatch.setattr(redis_client.settings, "REDIS_URL", "redis://localhost:6379/0")
    boom = _Boom()
    monkeypatch.setattr(redis_client, "Redis", boom)
    asyncio.run(RedisClient.connect())
    assert boom.calls == 0
    assert RedisClient.enabled is False and RedisClient.client is None
    assert RedisClient.get_client() is None


def test_desktop_disables_even_if_previously_enabled(monkeypatch):
    RedisClient.enabled = True
    monkeypatch.setenv("DONGAI_DESKTOP", "1")
    asyncio.run(RedisClient.connect())
    assert RedisClient.enabled is False


def test_desktop_degraded_ops_are_noops(monkeypatch):
    monkeypatch.setenv("DONGAI_DESKTOP", "1")
    asyncio.run(RedisClient.connect())

    async def go():
        await RedisClient.set("k", "v", ex=1)
        assert await RedisClient.get("k") is None
        await RedisClient.delete("k")
        await RedisClient.close()
    asyncio.run(go())


def test_non_desktop_still_attempts_connect(monkeypatch):
    monkeypatch.delenv("DONGAI_DESKTOP", raising=False)
    seen = {}

    class FakeRedis:
        async def ping(self):
            return True

    class Factory:
        @staticmethod
        def from_url(url, **k):
            seen["url"] = url
            return FakeRedis()

    monkeypatch.setattr(redis_client, "Redis", Factory)
    monkeypatch.setattr(redis_client.settings, "REDIS_URL", "redis://example:1/0")
    asyncio.run(RedisClient.connect())
    assert seen["url"] == "redis://example:1/0"
    assert RedisClient.enabled is True


def test_non_desktop_failure_degrades(monkeypatch):
    monkeypatch.delenv("DONGAI_DESKTOP", raising=False)

    class Factory:
        @staticmethod
        def from_url(url, **k):
            raise OSError("refused")

    monkeypatch.setattr(redis_client, "Redis", Factory)
    asyncio.run(RedisClient.connect())
    assert RedisClient.enabled is False and RedisClient.get_client() is None
