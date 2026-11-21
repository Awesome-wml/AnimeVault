"""视频模型的提示词能力表：每个模型吃哪种写法、一个小镜头最多撑多久、禁区怎么写。

分镜数据（台词、小镜头、时间）与模型无关；发给视频模型的那段文字由“档案”决定怎么渲染。
换模型、或同一模型升级后更听话了，只改这张表（或新增一份档案），不动分镜数据和拼装逻辑。

选档案：模型表 core/video_models.VIDEO_MODELS 的 prompt_profile 字段；环境变量 DONGAI_PROMPT_PROFILE 可整体覆盖
（用来拿同一批分镜做两种写法的出片对比）。

各字段的依据见 docs/prompt-opt-changelog.md 第 12 节；verified=False 的档案没有成片对比过。
"""
import os
from dataclasses import dataclass
from typing import Optional, Tuple

ENV_OVERRIDE = "DONGAI_PROMPT_PROFILE"


@dataclass(frozen=True)
class PromptProfile:
    key: str
    note: str
    max_beat_seconds: float = 8.0      # 单个小镜头最长多少秒；更长由代码拆成两个景别（模型撑不住会自己乱切）
    hook_seconds: float = 4.0          # 全片第一段第 1 个小镜头（钩子）最长多少秒，超了只提示
    max_beats: int = 5                 # 一段最多几个小镜头，超了只提示
    max_action_clauses: int = 3        # 一个小镜头的动作最多几个分句，超了提示“主动作太多”
    timestamp_style: str = "seconds"   # seconds：[0-4.9秒]；shot：[镜头1 0-4.9秒]
    # 提示词各块的顺序（靠前的权重更高）。块名见 core/video_prompt.assemble_video_prompt_ex
    section_order: Tuple[str, ...] = ("setting", "hard", "tail", "refs", "identity", "dialogue", "picture", "style", "forbid")
    negative_style: str = "full"       # full：完整禁区清单；lean：5 条以内、尽量写成正向描述
    verified: bool = False             # 是否用成片对比确认过


PROFILES = {
    # 现行写法：与此前线上行为逐字一致
    "seedance2": PromptProfile(
        key="seedance2", note="Seedance 2.x 现行写法：时间戳分段、完整禁区清单", verified=False),
    # 对照写法：风格与角色锁定前置、镜头编号 + 时间戳、禁区压到 5 条正向描述、小镜头上限 5 秒
    "seedance2-lean": PromptProfile(
        key="seedance2-lean", note="对照写法：风格与角色前置、镜头编号、禁区精简、小镜头不超过 5 秒",
        max_beat_seconds=5.0, hook_seconds=3.0, max_beats=5, timestamp_style="shot",
        section_order=("style", "identity", "setting", "hard", "tail", "refs", "picture", "dialogue", "forbid"),
        negative_style="lean", verified=False),
}
DEFAULT_PROFILE_KEY = "seedance2"


def get_profile(key: Optional[str]) -> PromptProfile:
    return PROFILES.get(key or "", PROFILES[DEFAULT_PROFILE_KEY])


def profile_for(model=None) -> PromptProfile:
    """model 可以是模型字典、模型 key 或 None。环境变量优先，其次模型表，最后缺省。"""
    env = (os.environ.get(ENV_OVERRIDE) or "").strip()
    if env in PROFILES:
        return PROFILES[env]
    if isinstance(model, dict):
        return get_profile(model.get("prompt_profile"))
    if isinstance(model, str) and model:
        from core.video_models import get_video_model
        return get_profile(get_video_model(model).get("prompt_profile"))
    return PROFILES[DEFAULT_PROFILE_KEY]


def time_label(profile: PromptProfile, index: int, start: str, end: str) -> str:
    """小镜头的时间标签。index 从 1 起；start/end 是已格式化好的秒数。"""
    if profile.timestamp_style == "shot":
        return f"[镜头{index} {start}-{end}秒]"
    return f"[{start}-{end}秒]"
