"""豆包网页「视频生成」可选模型（Seedance 系列）。

一条分镜段 = 一次视频生成，段时长目标取所选模型的 max_duration，拆分镜模板的时长参数从这里派生，
换模型后拆分镜自动按新模型的时长装段。

待真机确认（豆包账号当前登出，未能实测）：
- min_duration：网页时长滑块的最小值，暂按 4 秒；
- Seedance 2.0 Mini 的额度倍数，暂按 1 倍；
- 各模型 max_duration 均按 15 秒（Fast 已实测滑块最右为 15s）。
"""
from typing import Dict, List, Optional

import math

from core.pacing import CHARS_PER_SECOND, CONTENT_MARGIN_LOW_SECONDS, SPEECH_MARGIN_SECONDS, fmt_number
from core.shot_timing import spoken_chars

# 语速与余量只在 core/pacing.py 定义（R5）：段内台词朗读约 max-4 到 max-2 秒，字数 = 秒数 × CHARS_PER_SECOND
CONTENT_MARGIN_LOW = int(CONTENT_MARGIN_LOW_SECONDS)
CONTENT_MARGIN_HIGH = int(SPEECH_MARGIN_SECONDS)   # 台词预算上限：max-2 秒，留 2 秒给动作起收（= shot_timing.SPEECH_MARGIN）
SHORT_SEGMENT_SECONDS = 6       # 场景末尾补镜后仍不足这么多秒时，才按实际所需时长出段

IMAGE_TYPES = ["jpg", "jpeg", "png", "webp", "apng"]
VIDEO_TYPES = ["mp4", "mov"]

VIDEO_MODELS: List[Dict] = [
    {
        "key": "seedance-2.0-fast",
        "name": "Seedance 2.0 Fast",
        "note": "日常使用，默认",
        "max_duration": 15,
        "min_duration": 4,          # 待真机确认
        "cost_multiplier": 1,
        "reference_types": IMAGE_TYPES + VIDEO_TYPES,
        "max_files": 10,
        "prompt_profile": "seedance2",   # 提示词写法档案，见 core/prompt_profiles.py
        "confirmed": {"max_duration": True, "min_duration": False, "cost_multiplier": True},
    },
    {
        "key": "seedance-2.0",
        "name": "Seedance 2.0",
        "note": "2 倍消耗",
        "max_duration": 15,
        "min_duration": 4,          # 待真机确认
        "cost_multiplier": 2,
        "reference_types": list(IMAGE_TYPES),
        "max_files": 10,
        "prompt_profile": "seedance2",   # 提示词写法档案，见 core/prompt_profiles.py
        "confirmed": {"max_duration": False, "min_duration": False, "cost_multiplier": True},
    },
    {
        "key": "seedance-2.0-mini",
        "name": "Seedance 2.0 Mini",
        "note": "轻量",
        "max_duration": 15,
        "min_duration": 4,          # 待真机确认
        "cost_multiplier": 1,       # 待真机确认
        "reference_types": list(IMAGE_TYPES),
        "max_files": 10,
        "prompt_profile": "seedance2",   # 提示词写法档案，见 core/prompt_profiles.py
        "confirmed": {"max_duration": False, "min_duration": False, "cost_multiplier": False},
    },
    {
        "key": "seedance-2.5",
        "name": "Seedance 2.5",
        "note": "5 倍消耗",
        "max_duration": 15,
        "min_duration": 4,          # 待真机确认
        "cost_multiplier": 5,
        "reference_types": list(IMAGE_TYPES),
        "max_files": 10,
        "prompt_profile": "seedance2",   # 提示词写法档案，见 core/prompt_profiles.py
        "confirmed": {"max_duration": False, "min_duration": False, "cost_multiplier": True},
    },
]

DEFAULT_VIDEO_MODEL_KEY = "seedance-2.0-fast"
_BY_KEY = {m["key"]: m for m in VIDEO_MODELS}


def list_video_models() -> List[Dict]:
    return [dict(m) for m in VIDEO_MODELS]


def is_valid_model_key(key: Optional[str]) -> bool:
    return bool(key) and key in _BY_KEY


def get_video_model(key: Optional[str] = None) -> Dict:
    """按 key 取模型；为空或未知时回退默认（Fast）。"""
    return dict(_BY_KEY.get(key or "", _BY_KEY[DEFAULT_VIDEO_MODEL_KEY]))


def accepts_file(model: Dict, path: str) -> bool:
    """该模型的参考素材是否接受这个文件（按扩展名）。都不接受音频。"""
    ext = (path or "").rsplit(".", 1)[-1].lower()
    return ext in (model.get("reference_types") or IMAGE_TYPES)


def segment_params(model: Dict) -> Dict:
    """拆分镜模板用的时长参数：段时长、内容区间、每段字数、最短时长、语速（模板里“每秒 {chars_per_second} 字”）。"""
    seg = int(model["max_duration"])
    low = max(seg - CONTENT_MARGIN_LOW, 1)
    high = max(seg - CONTENT_MARGIN_HIGH, low)
    return {
        "model_name": model["name"],
        "segment_seconds": seg,
        "min_seconds": int(model["min_duration"]),
        "content_low": low,
        "content_high": high,
        "chars_per_second": fmt_number(CHARS_PER_SECOND),
        "chars_low": int(low * CHARS_PER_SECOND),
        "chars_high": int(high * CHARS_PER_SECOND),
        "chars_per_segment": int(round((low + high) / 2 * CHARS_PER_SECOND)),
        "short_seconds": SHORT_SEGMENT_SECONDS,
    }


def segment_budget(novel_text: str, model: Dict) -> Dict:
    """按全文朗读量给模型一个段数预算：全文朗读秒数 / 每段内容上限，向上取整。"""
    seconds = spoken_chars(novel_text) / CHARS_PER_SECOND
    high = segment_params(model)["content_high"]
    return {"novel_seconds": int(round(seconds)), "segment_count_hint": max(int(math.ceil(seconds / high)), 1)}
