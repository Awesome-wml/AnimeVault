"""长任务后台化（core/sse）：页面断开任务照跑、可查进度、可重新接上、同 key 不重复跑。"""
import asyncio
import json

import pytest

from core import sse


@pytest.fixture(autouse=True)
def clean_tasks():
    sse._TASKS.clear()
    yield
    sse._TASKS.clear()


async def _collect(resp, limit=50):
    out = []
    async for chunk in resp.body_iterator:
        for line in str(chunk).splitlines():
            if line.startswith("data: "):
                out.append(json.loads(line[6:]))
        if out and out[-1]["type"] in ("done", "error") or len(out) >= limit:
            break
    return out


def test_task_finishes_and_keeps_result_even_if_nobody_reads_the_stream(monkeypatch):
    monkeypatch.setattr(sse, "POLL_SECONDS", 0.01)
    ran = []

    async def build(report):
        await report(10, chunk=1, total=2)
        await asyncio.sleep(0.02)
        ran.append(1)
        return "成功拆分 3 个镜头", {"count": 3}

    async def main():
        state = sse.start_task(build, key="split:p1:default", owner="u1", kind="拆分镜")
        assert state["status"] == "running" and state["task"] is not None      # 任务表持有任务对象
        await asyncio.sleep(0.08)                                               # 没有任何人接进度流
        return state

    state = asyncio.run(main())
    assert ran == [1] and state["status"] == "done" and state["data"] == {"count": 3} and state["task"] is None
    view = sse.list_tasks(owner="u1")[0]
    assert view["status"] == "done" and view["message"] == "成功拆分 3 个镜头" and "data" not in view
    assert sse.public_view(state, with_data=True)["data"] == {"count": 3}
    assert sse.list_tasks(owner="别人") == [] and sse.get_task(state["id"], owner="别人") is None


def test_stream_reports_task_id_progress_and_done_and_can_be_reattached(monkeypatch):
    monkeypatch.setattr(sse, "POLL_SECONDS", 0.01)

    async def build(report):
        await report(100, chunk=1, total=3)
        await asyncio.sleep(0.05)
        await report(900, chunk=3, total=3)
        await asyncio.sleep(0.05)
        return "ok", {"n": 1}

    async def main():
        first = await sse.run_with_sse(build, key="k", owner="u1")
        events = await _collect(first)
        state = sse.find_running("k") or next(iter(sse._TASKS.values()))
        again = await _collect(sse.stream_task(state))                          # 跑完之后再接：立刻拿到结果
        return events, again

    events, again = asyncio.run(main())
    assert events[0]["type"] == "task" and events[0]["key"] == "k" and events[0]["task_id"]
    assert {"type": "progress", "chars": 100, "chunk": 1, "total": 3} in events
    assert events[-1] == {"type": "done", "message": "ok", "data": {"n": 1}}
    assert [e["type"] for e in again] == ["task", "done"]


def test_same_key_attaches_to_running_task_instead_of_starting_another(monkeypatch):
    monkeypatch.setattr(sse, "POLL_SECONDS", 0.01)
    starts = []

    async def build(report):
        starts.append(1)
        await asyncio.sleep(0.05)
        return "ok", {}

    async def main():
        a = sse.start_task(build, key="split:p1:ep1", owner="u1")
        b = sse.start_task(build, key="split:p1:ep1", owner="u1")              # 重复点击
        c = sse.start_task(build, key="split:p1:ep2", owner="u1")              # 另一集：各跑各的
        await asyncio.sleep(0.12)
        d = sse.start_task(build, key="split:p1:ep1", owner="u1")              # 上一个跑完后：可以再起
        await asyncio.sleep(0.12)
        return a, b, c, d

    a, b, c, d = asyncio.run(main())
    assert a is b and c is not a and d is not a and len(starts) == 3


def test_error_is_kept_on_the_task_and_streamed(monkeypatch):
    monkeypatch.setattr(sse, "POLL_SECONDS", 0.01)

    async def build(report):
        raise ValueError("模型输出被截断")

    async def main():
        return await _collect(await sse.run_with_sse(build, key="k2", owner="u1"))

    events = asyncio.run(main())
    assert events[-1] == {"type": "error", "message": "模型输出被截断"}
    assert sse.list_tasks(owner="u1", key="k2")[0]["status"] == "error"


def test_finished_tasks_expire_but_running_ones_stay(monkeypatch):
    sse._TASKS["old"] = {"id": "old", "key": "a", "owner": "u", "kind": "", "status": "done", "progress": {}, "message": "",
                         "data": None, "started_at": 0, "finished_at": 1, "task": None}
    sse._TASKS["run"] = {"id": "run", "key": "b", "owner": "u", "kind": "", "status": "running", "progress": {}, "message": "",
                         "data": None, "started_at": 0, "finished_at": None, "task": None}
    assert [t["task_id"] for t in sse.list_tasks(owner="u")] == ["run"]
