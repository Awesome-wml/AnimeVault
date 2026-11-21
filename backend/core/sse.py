"""SSE 流式响应公共包装：把异步生成任务包成 text/event-stream，过程中可推进度心跳。

长任务（拆分镜、提取资产、转剧本）在后台跑，不依赖页面连接：
- 任务对象登记在进程内的任务表里并被持有（没人持有的 asyncio 任务可能被垃圾回收，跑到一半就没了）；
- 页面关掉、断线后任务继续跑完并落库；重新打开可以用任务 key 查到进度或结果，也可以重新接上进度流；
- 同一个 key 的任务还在跑时再发一次请求，不会再起一个，而是接到正在跑的那个上（防止重复点击跑两遍、
  后跑完的把先跑完的结果覆盖掉）。
任务表只在内存里：后端重启后正在跑的任务就没了（它们本来也随进程结束），已落库的结果不受影响。
"""
import asyncio
import json
import time
import uuid
from typing import Dict, List, Optional

from fastapi.responses import StreamingResponse

SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}

POLL_SECONDS = 0.5           # 进度流多久看一次任务状态
PING_SECONDS = 15            # 这么久没有新进度就发一次心跳，避免代理或客户端判定断连
KEEP_FINISHED_SECONDS = 3600  # 跑完的任务在任务表里留多久（给重新打开页面的人看结果）
MAX_FINISHED = 50

_TASKS: Dict[str, dict] = {}


def sse_event(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _prune() -> None:
    """清掉过期的已完成任务；已完成的太多时只留最近的 MAX_FINISHED 个。正在跑的不动。"""
    now = time.time()
    done = sorted((t for t in _TASKS.values() if t["status"] != "running"),
                  key=lambda t: t["finished_at"] or 0, reverse=True)
    for i, t in enumerate(done):
        if i >= MAX_FINISHED or now - (t["finished_at"] or now) > KEEP_FINISHED_SECONDS:
            _TASKS.pop(t["id"], None)


def find_running(key: Optional[str]) -> Optional[dict]:
    if not key:
        return None
    return next((t for t in _TASKS.values() if t["key"] == key and t["status"] == "running"), None)


def public_view(t: dict, with_data: bool = False) -> dict:
    """任务状态给接口看的样子（不含内部对象）。with_data：带上完成后的结果数据（可能很大）。"""
    out = {"task_id": t["id"], "key": t["key"], "kind": t["kind"], "status": t["status"],
           "progress": dict(t["progress"]), "message": t["message"],
           "started_at": t["started_at"], "finished_at": t["finished_at"]}
    if with_data and t["status"] == "done":
        out["data"] = t["data"]
    return out


def list_tasks(owner: Optional[str] = None, key: Optional[str] = None, prefix: Optional[str] = None) -> List[dict]:
    """任务表里的任务（新的在前）。owner：只看这个用户的；key 精确匹配，prefix 按前缀匹配。"""
    _prune()
    items = [t for t in _TASKS.values()
             if (owner is None or t["owner"] == owner)
             and (key is None or t["key"] == key)
             and (prefix is None or str(t["key"] or "").startswith(prefix))]
    return [public_view(t) for t in sorted(items, key=lambda t: t["started_at"], reverse=True)]


def get_task(task_id: str, owner: Optional[str] = None) -> Optional[dict]:
    t = _TASKS.get(task_id)
    return t if t and (owner is None or t["owner"] == owner) else None


def start_task(build_task, key: Optional[str] = None, owner: Optional[str] = None, kind: str = "") -> dict:
    """登记并启动一个后台任务，返回任务状态对象。同一个 key 已有任务在跑时直接返回那个，不再起新的。"""
    running = find_running(key)
    if running:
        return running
    _prune()
    state = {"id": uuid.uuid4().hex, "key": key, "owner": owner, "kind": kind, "status": "running",
             "progress": {"chars": 0, "chunk": None, "total": None}, "message": "", "data": None,
             "started_at": time.time(), "finished_at": None, "task": None}

    async def _report(chars: int, chunk: int = None, total: int = None):
        state["progress"] = {"chars": chars, "chunk": chunk, "total": total}

    async def worker():
        try:
            message, data = await build_task(_report)
            state.update(status="done", message=message, data=data)
        except Exception as e:      # 记在任务上推给前端，不在 SSE 里抛 500
            state.update(status="error", message=str(e))
        finally:
            state["finished_at"] = time.time()
            state["task"] = None     # 跑完就不用再持有任务对象了

    _TASKS[state["id"]] = state
    state["task"] = asyncio.create_task(worker())      # 任务表持有它，页面断开也不会被回收
    return state


def stream_task(state: dict) -> StreamingResponse:
    """把一个任务的进度做成 SSE 流。谁来接都行（发起的页面，或后来重新打开的页面）；断开不影响任务。"""
    async def gen():
        yield sse_event({"type": "task", "task_id": state["id"], "key": state["key"]})
        last, quiet = None, 0.0
        while True:
            if state["status"] == "done":
                yield sse_event({"type": "done", "message": state["message"], "data": state["data"]})
                return
            if state["status"] == "error":
                yield sse_event({"type": "error", "message": state["message"]})
                return
            cur = (state["progress"]["chars"], state["progress"]["chunk"], state["progress"]["total"])
            if cur != last:
                last, quiet = cur, 0.0
                event = {"type": "progress", "chars": cur[0]}
                if cur[1]:
                    event.update(chunk=cur[1], total=cur[2])
                yield sse_event(event)
            elif quiet >= PING_SECONDS:
                quiet = 0.0
                yield sse_event({"type": "ping"})
            await asyncio.sleep(POLL_SECONDS)
            quiet += POLL_SECONDS

    return StreamingResponse(gen(), media_type="text/event-stream", headers=SSE_HEADERS)


async def run_with_sse(build_task, key: Optional[str] = None, owner: Optional[str] = None,
                       kind: str = "") -> StreamingResponse:
    """把一个异步任务放到后台跑，并返回它的进度流。

    build_task(report) 是协程函数：
      - report(chars, chunk=None, total=None) 上报已接收字符数（推 progress 事件）；分块任务再带第几块 / 共几块；
      - 返回 (message, data)，完成后推 done 事件；
      - 抛异常则推 error 事件。
    key：任务的身份（如 “split:作品:集”）。给了 key，同一个 key 的任务在跑时再次调用会接到那个任务上；
    owner：发起的用户，查任务时按它隔离；kind：任务类型，给前端显示用。
    """
    return stream_task(start_task(build_task, key=key, owner=owner, kind=kind))
