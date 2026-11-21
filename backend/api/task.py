"""后台任务查询：拆分镜、提取资产、转剧本这些长任务的进度和结果。

页面关掉后任务照样跑完；重新打开时用这里的接口看有没有正在跑的、接回进度流、取结果。
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from api.auth import get_current_user
from core import sse
from models.schema import ResponseModel

router = APIRouter(prefix="/api/tasks", tags=["后台任务"])


@router.get("")
async def list_my_tasks(project_id: Optional[str] = None, user: dict = Depends(get_current_user)):
    """我的后台任务（正在跑的和最近一小时跑完的）。project_id：只看这个作品的。"""
    tasks = sse.list_tasks(owner=str(user["_id"]))
    if project_id:
        tasks = [t for t in tasks if f":{project_id}:" in f"{t['key']}:"]
    return ResponseModel(data={"tasks": tasks})


@router.get("/{task_id}")
async def task_detail(task_id: str, user: dict = Depends(get_current_user)):
    """一个任务的状态；已完成的带上结果数据。"""
    t = sse.get_task(task_id, owner=str(user["_id"]))
    if not t:
        raise HTTPException(status_code=404, detail="任务不存在或已过期（结果已落库的话刷新页面即可看到）")
    return ResponseModel(data=sse.public_view(t, with_data=True))


@router.get("/{task_id}/events")
async def task_events(task_id: str, user: dict = Depends(get_current_user)):
    """重新接上一个任务的进度流（SSE）。任务已经跑完会立刻收到 done 或 error。"""
    t = sse.get_task(task_id, owner=str(user["_id"]))
    if not t:
        raise HTTPException(status_code=404, detail="任务不存在或已过期")
    return sse.stream_task(t)
