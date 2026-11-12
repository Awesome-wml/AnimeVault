"""场景的剧情状态与视角：state_note（剧情发生时的关键物件状态）+ views（同一空间的多个机位，每个视角一张无人场景图）。

场景文档字段：
    state_note  ≤40 字，剧情发生时该场景关键物件状态（已碎、已倒、已点燃）；description 已按这个状态写；可为空
    views       [{name, camera, image_path}]，每个视角一张图；camera ≤30 字写机位朝向
    description 旧字段，保留
    image_path  旧字段 = 第一视角的图，旧代码与旧数据照旧可用

旧数据兼容：没有 views 的场景视为单视角，图取 image_path。所有读取视角的地方都经过这里。
"""
from __future__ import annotations

from typing import Dict, List, Optional

SINGLE_VIEW_NAME = "默认视角"
STATE_NOTE_MAX = 40
CAMERA_MAX = 30
MAX_VIEWS = 6


def clean_state_note(value) -> str:
    return str(value or "").strip()[:STATE_NOTE_MAX]


def normalize_view(view, index: int = 0) -> Optional[Dict]:
    if isinstance(view, str):
        view = {"camera": view}
    if not isinstance(view, dict):
        return None
    name = str(view.get("name") or "").strip()
    camera = str(view.get("camera") or view.get("description") or "").strip()[:CAMERA_MAX]
    if not name and not camera:
        return None
    return {"name": name or f"视角{index + 1}", "camera": camera, "image_path": view.get("image_path") or None}


def normalize_views(views) -> List[Dict]:
    out: List[Dict] = []
    for v in views if isinstance(views, (list, tuple)) else []:
        n = normalize_view(v, len(out))
        if n and len(out) < MAX_VIEWS:
            out.append(n)
    return out


def scene_views(scene: Dict) -> List[Dict]:
    """场景的视角列表（至少 1 个）。旧数据：单视角，图取 image_path。"""
    views = normalize_views(scene.get("views"))
    if views:
        if not views[0].get("image_path") and scene.get("image_path"):
            views[0]["image_path"] = scene["image_path"]
        return views
    return [{"name": SINGLE_VIEW_NAME, "camera": "", "image_path": scene.get("image_path") or None}]


def scene_doc_fields(scene: Dict) -> Dict:
    """模型提取结果 → 入库字段（state_note / views / image_path）；没给 views 则单视角。"""
    views = normalize_views(scene.get("views")) or [
        {"name": SINGLE_VIEW_NAME, "camera": "", "image_path": None}]
    return {"state_note": clean_state_note(scene.get("state_note")), "views": views,
            "image_path": views[0].get("image_path")}


def view_index_of(scene: Dict, index: Optional[int]) -> int:
    n = len(scene_views(scene))
    try:
        i = int(index or 0)
    except (TypeError, ValueError):
        i = 0
    return i if 0 <= i < n else 0


def set_view_image(scene: Dict, index: int, img_path: str) -> Dict:
    """写回某视角的图，返回 $set 字段：views 整体 + 第一视角时同步 image_path。"""
    views = scene_views(scene)
    i = view_index_of(scene, index)
    views[i]["image_path"] = img_path
    update = {"views": views}
    if i == 0:
        update["image_path"] = img_path
    return update


def merge_views_update(scene: Dict, views) -> List[Dict]:
    """接口更新 views：请求没带 image_path 的视角按下标沿用原图；至少保留 1 个。"""
    old = scene_views(scene)
    new = normalize_views(views)
    for i, v in enumerate(new):
        if not v.get("image_path") and i < len(old):
            v["image_path"] = old[i].get("image_path")
    return new or old[:1]


def public_views(scene: Dict) -> List[Dict]:
    return scene_views(scene)
