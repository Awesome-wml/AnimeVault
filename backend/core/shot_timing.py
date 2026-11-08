"""分镜时长规则：模板文字和落库兜底共用同一套常量与估算函数。

时长 ≈ 台词/旁白朗读时长（中文约每秒 4 到 5 字，按 4.5 计）+ 1 秒动作与反应余量；
短句 3 到 5 秒；大动作或气势镜头可在估算基础上放宽，最长 15 秒。
"""
import math
import re

CHARS_PER_SECOND = 4.5      # 中文朗读语速
REACTION_SECONDS = 1        # 动作与反应余量
MIN_SECONDS = 3
MAX_SECONDS = 15
ACTION_EXTRA_SECONDS = 4    # 大动作/气势镜头最多在估算上再放宽的秒数
DEVIATION_RATIO = 2         # 模型时长超过估算的这个倍数视为明显偏离
CORRECTED_EXTRA_SECONDS = 2  # 明显偏离时收回到“估算 + 这点余量”

# 不计入朗读字数的标点与空白
_NON_SPOKEN = re.compile(r"[\s，。！？、；：,.!?;:…—\-“”‘’「」『』《》（）()【】\[\]\"']")


def spoken_chars(text: str) -> int:
    """朗读字数：去掉标点和空白后的字符数。"""
    return len(_NON_SPOKEN.sub("", text or ""))


def estimate_duration(text: str) -> int:
    """按朗读字数估算单镜时长（秒）。"""
    est = math.ceil(spoken_chars(text) / CHARS_PER_SECOND) + REACTION_SECONDS
    return int(min(max(est, MIN_SECONDS), MAX_SECONDS))


def normalize_duration(model_value, text: str) -> float:
    """校正模型给的时长：缺失或读不完时用估算值；超过估算 2 倍时收回到“估算 + 2 秒”；上限 15 秒。"""
    est = estimate_duration(text)
    try:
        d = float(model_value)
    except (TypeError, ValueError):
        return float(est)
    if d < est:
        d = est
    elif d > est * DEVIATION_RATIO:
        d = est + CORRECTED_EXTRA_SECONDS
    return float(min(max(d, MIN_SECONDS), MAX_SECONDS))


# 注入分镜模板的时长规则（与上面的常量保持一致）
DURATION_RULE = (
    f"duration：按 text 的朗读时长定，中文约每秒 4 到 5 字，再加 {REACTION_SECONDS} 到 2 秒动作和反应余量；"
    f"例如 7 个字的短句约 3 到 4 秒，20 个字约 6 秒，40 个字约 10 秒。短句 {MIN_SECONDS} 到 5 秒；"
    f"只有大动作或气势镜头（如异象爆发、龙影冲天）才可在朗读时长上再放宽 2 到 {ACTION_EXTRA_SECONDS} 秒，"
    f"任何单元最长 {MAX_SECONDS} 秒。不要把短句凑成长镜头。"
)
