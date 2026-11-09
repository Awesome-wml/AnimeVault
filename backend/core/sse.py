"""SSE 流式响应公共包装：把异步生成任务包成 text/event-stream，过程中可推进度心跳。"""
import asyncio
import json

from fastapi.responses import StreamingResponse

SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}

_SENTINEL = object()


def sse_event(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def run_with_sse(build_task) -> StreamingResponse:
    """把一个异步任务包成 SSE 响应。

    build_task(report) 是协程函数：
      - report(chars, chunk=None, total=None) 可在流式接收过程中上报已接收字符数（推 progress 事件）；
        分块任务再带上第几块 / 共几块（事件里多 chunk、total 两个字段）；
      - 返回 (message, data)，完成后推 done 事件；
      - 抛异常则推 error 事件。
    """
    queue: "asyncio.Queue" = asyncio.Queue()

    async def worker():
        try:
            result = await build_task(_report)
            await queue.put(("done", result))
        except Exception as e:  # 推给前端，不在 SSE 里抛 500
            await queue.put(("error", str(e)))
        finally:
            await queue.put(_SENTINEL)

    async def _report(chars: int, chunk: int = None, total: int = None):
        await queue.put(("progress", (chars, chunk, total)))

    async def gen():
        asyncio.create_task(worker())
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=15)
            except asyncio.TimeoutError:
                # 等待首字/长任务期间发心跳，避免代理或客户端判定断连
                yield sse_event({"type": "ping"})
                continue
            if item is _SENTINEL:
                break
            kind, payload = item
            if kind == "progress":
                chars, chunk, total = payload
                event = {"type": "progress", "chars": chars}
                if chunk:
                    event.update(chunk=chunk, total=total)
                yield sse_event(event)
            elif kind == "done":
                message, data = payload
                yield sse_event({"type": "done", "message": message, "data": data})
            elif kind == "error":
                yield sse_event({"type": "error", "message": payload})

    return StreamingResponse(gen(), media_type="text/event-stream", headers=SSE_HEADERS)
