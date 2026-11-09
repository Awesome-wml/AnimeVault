"""豆包视频模式「时长」滑块换算（纯函数，不依赖浏览器，便于单测）。

已实测（1280 视口）：把滑块拖到 x=925 显示 15s，即轨道右端。轨道左端与最小时长没实测到，
运行时优先读滑块所在轨道的真实位置和 aria-valuemin / aria-valuemax；读不到时用下面的估计值。
**待真机验证**：DEFAULT_TRACK_LEFT_X、滑块最小值（core/video_models.py 的 min_duration）。
"""
import re
from typing import Optional

DEFAULT_TRACK_RIGHT_X = 925.0   # 实测：拖到这里显示 15s
DEFAULT_TRACK_LEFT_X = 685.0    # 估计：弹层内轨道约 240px 宽，待真机验证
DEFAULT_MIN_SECONDS = 4         # 估计，待真机验证
DEFAULT_MAX_SECONDS = 15

_LABEL = re.compile(r"(\d+(?:\.\d+)?)\s*(?:s|秒)", re.I)


def clamp_duration(duration, vmin: float = DEFAULT_MIN_SECONDS, vmax: float = DEFAULT_MAX_SECONDS) -> int:
    """时长取整并钳到滑块范围；非法值按最大值。"""
    try:
        d = float(duration)
    except (TypeError, ValueError):
        return int(vmax)
    if d != d:  # NaN
        return int(vmax)
    return int(round(min(max(d, vmin), vmax)))


def duration_to_ratio(duration, vmin: float = DEFAULT_MIN_SECONDS, vmax: float = DEFAULT_MAX_SECONDS) -> float:
    """时长 → 滑块位置比例（0 = 最左/最小，1 = 最右/最大）。"""
    if vmax <= vmin:
        return 1.0
    return (clamp_duration(duration, vmin, vmax) - vmin) / (vmax - vmin)


def slider_x(duration, track_left: Optional[float] = None, track_right: Optional[float] = None,
             vmin: float = DEFAULT_MIN_SECONDS, vmax: float = DEFAULT_MAX_SECONDS) -> float:
    """时长 → 要把滑块拖到的横坐标。轨道两端读不到时用默认估计（右端 925 已实测为 15s）。"""
    left = DEFAULT_TRACK_LEFT_X if track_left is None else float(track_left)
    right = DEFAULT_TRACK_RIGHT_X if track_right is None else float(track_right)
    return round(left + (right - left) * duration_to_ratio(duration, vmin, vmax), 1)


def parse_duration_label(text: str) -> Optional[int]:
    """从按钮 / 滑块文字里读出秒数，如“15s”“10 秒”；读不到返回 None。"""
    m = _LABEL.search(text or "")
    return int(round(float(m.group(1)))) if m else None


def arrow_steps(current: Optional[int], target: int) -> int:
    """拖完后读回的值与目标差几格：正数按右方向键，负数按左方向键（滑块步长 1 秒）。"""
    if current is None:
        return 0
    return int(target) - int(current)
