"""节奏与时长口径的唯一数值源（分析报告 P4/R5，方案 §4.3）。

任何模板文字、估算函数、校验规则都从这里取数，不得各自定义：
- core.shot_timing / core.video_models / core.prompt_tpl 的语速、余量常量全部 import 自此处；
- 注册表模板（constraints.json split_shots*）里写“每秒 {chars_per_second} 字”，由 video_models.segment_params 注入；
- 前端“目标时长 → 台词字数”的提示通过 /api/config/video-models 的 pacing 字段读同一个数。

此前的口径是分裂的：拆分镜与 shot_timing 按 6 字/秒装段（8274680），剧本篇幅预算 prompt_tpl 仍按 4.5，
用户设 300 秒目标 → 剧本给 1350 字 → 拆段按 6 字/秒只得约 225 秒，成片比目标短约 25%。

MEASURED 标 False 的数值还没有用真实视频模型测过：
- chars_per_second：待真机测语速后确认。做法：生成 2–3 条 15 秒段，数实际说出的字 / 实际发声秒数，
  在 4.5–6.0 之间定值。6.0 是快口播语速，15 秒段塞 78 字有赶词、吞尾句、视频不够长的风险，
  未测前按方案 §10 D1 先取折中 5.0。
- first_frame_hold_seconds：原为 2 秒（video_prompt 首帧承接块），0.5 秒开口的首句台词会被“2 秒内不许变表情”压住，
  先按 1 秒（R10），hold 1 秒 vs 2 秒各 2 段真机对比后定。
测定后只改这里，并把 MEASURED 翻成 True、在 docs/prompt-opt-changelog.md 记录依据。
"""

CHARS_PER_SECOND = 5.0            # 中文朗读语速（字/秒）。待真机测语速后确认（见模块说明）
SPEECH_MARGIN_SECONDS = 2.0       # 台词预算：段内朗读字数 ≤ (段时长 - 这点) × CHARS_PER_SECOND，留给动作起收
CONTENT_MARGIN_LOW_SECONDS = 4.0  # 拆分镜模板“本段朗读约 max-4 到 max-2 秒”的下限余量
FIRST_FRAME_HOLD_SECONDS = 1.0    # 首帧承接后保持姿势、站位与朝向的秒数（可开口说话、做微表情）。待真机

MEASURED = {"chars_per_second": False, "first_frame_hold_seconds": False}

# 语速按视频模型取：模型的提示词档案（core/prompt_profiles）可以给自己的语速，没给就用上面的全局值。
# 计算函数都读 current_rate()；入口处（装段、重排时间、分镜列表）用 use_rate(rate_for(模型)) 把语速设好。
# 用 ContextVar：并发请求、并行拆块各用各的语速，互不影响。
import contextlib as _contextlib
import contextvars as _contextvars

_RATE: "_contextvars.ContextVar" = _contextvars.ContextVar("dongai_chars_per_second", default=None)


def current_rate() -> float:
    """当前生效的语速（字/秒）。没有设过就是全局缺省值。"""
    return float(_RATE.get() or CHARS_PER_SECOND)


def rate_for(model=None) -> float:
    """这个视频模型（字典、key 或 None）的语速。"""
    from core.prompt_profiles import profile_for
    return float(profile_for(model).chars_per_second or CHARS_PER_SECOND)


@_contextlib.contextmanager
def use_rate(rate=None):
    """在这段代码里按给定语速算时间；传 None 表示用全局缺省值。"""
    token = _RATE.set(float(rate) if rate else None)
    try:
        yield
    finally:
        _RATE.reset(token)


def fmt_number(x) -> str:
    """数字进文案：5.0 → "5"，4.5 → "4.5"。"""
    f = float(x)
    return str(int(f)) if f.is_integer() else f"{f:g}"


def chars_for_seconds(seconds: float) -> int:
    """这么多秒能说多少字（向下取整）。"""
    return int(float(seconds) * current_rate())


def seconds_for_chars(chars: int) -> float:
    """这么多字要说多少秒。"""
    return float(chars) / current_rate()


def speech_seconds_for_target(target_seconds: float, segment_seconds: float = 15.0) -> float:
    """成片目标时长里能装多少秒台词。

    每个视频段只装 (段时长 - SPEECH_MARGIN_SECONDS) 秒台词（与 video_models.segment_params 的 content_high 一致），
    所以剧本台词预算不能按“目标时长全部在说话”算：300 秒目标、15 秒段 → 台词约 260 秒 → 约 20 段 ≈ 300 秒。
    此前按 300 秒全说话给 1500 字，拆出约 23 段 ≈ 345 秒，成片比目标长约 15%。
    """
    seg = float(segment_seconds or 15.0)
    ratio = max(seg - SPEECH_MARGIN_SECONDS, 1.0) / seg
    return float(target_seconds) * ratio


def pacing_payload() -> dict:
    """给接口/前端用的只读口径（/api/config/video-models 的 pacing 字段）。"""
    return {
        "chars_per_second": current_rate(),
        "speech_margin_seconds": SPEECH_MARGIN_SECONDS,
        "first_frame_hold_seconds": FIRST_FRAME_HOLD_SECONDS,
        "measured": dict(MEASURED),
    }


def apply_rate(rate=None) -> None:
    """把当前请求剩下的计算都设成这个语速（不恢复）。只在一次请求的处理函数里用：每个请求是独立的上下文。"""
    _RATE.set(float(rate) if rate else None)
