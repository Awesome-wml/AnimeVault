"""导出剪映 / CapCut 草稿的平台相关部分：每段实际时长与宽高、跨平台打开剪辑软件。"""
import logging
import os
import subprocess
import sys
from typing import Optional, Tuple

from core.ffmpeg_tool import probe_video

logger = logging.getLogger(__name__)

DEFAULT_SIZE = (1280, 720)


def clip_timing(path: str, shot: Optional[dict], default_us: int, probe=probe_video) -> Tuple[int, int, int]:
    """(时长微秒, 宽, 高)。优先 ffmpeg 探测实际成片；探测不到时长退回分镜 duration，再退回模板时长；
    宽高探测不到用 1280×720。"""
    seconds = width = height = None
    try:
        seconds, width, height = probe(path)
    except Exception as e:  # noqa: BLE001  ffmpeg 缺失或文件损坏都不能让导出失败
        logger.warning("探测成片时长/宽高失败 %s: %s", path, e)
    if not seconds or seconds <= 0:
        try:
            seconds = float((shot or {}).get("duration") or 0) or None
        except (TypeError, ValueError):
            seconds = None
    dur_us = int(round(seconds * 1_000_000)) if seconds else int(default_us)
    if not width or not height:
        width, height = DEFAULT_SIZE
    return dur_us, int(width), int(height)


# 剪映 / CapCut 的应用名（macOS open -a）与 Windows 常见安装位置（相对 %LOCALAPPDATA%）
_APPS = {
    "jianying": {"mac": "VideoFusion-macOS", "win": [r"JianyingPro\Apps\JianyingPro.exe"]},
    "capcut": {"mac": "CapCut", "win": [r"CapCut\Apps\CapCut.exe"]},
}


def open_editor_app(app: str, platform: Optional[str] = None, env: Optional[dict] = None,
                    popen=subprocess.Popen, exists=os.path.exists) -> bool:
    """尽力打开剪映 / CapCut，草稿已经写好，打不开只记日志、返回 False，不让接口报错。

    原来固定 `open -a`，Windows 上直接抛异常、导出接口 500。
    """
    platform = platform or sys.platform
    env = os.environ if env is None else env
    spec = _APPS.get(app)
    if not spec:
        return False
    try:
        if platform == "darwin":
            popen(["open", "-a", spec["mac"]])
            return True
        if platform.startswith("win"):
            base = env.get("LOCALAPPDATA") or ""
            for rel in spec["win"]:
                exe = os.path.join(base, rel)
                if base and exists(exe):
                    popen([exe])
                    return True
            logger.info("没有找到 %s 安装位置，草稿已写好，请手动打开", app)
            return False
        logger.info("当前平台 %s 不支持自动打开 %s，草稿已写好", platform, app)
        return False
    except Exception as e:  # noqa: BLE001
        logger.warning("打开 %s 失败（草稿已写好）: %s", app, e)
        return False


def seam_trims(shots: list, durations_us: list) -> list:
    """每段在时间线上末尾要剪掉多少微秒。

    续接段（生成时带了上一段尾帧，prev_frame_attached）的第 0 帧是上一段倒数 PREV_FRAME_OFFSET_SECONDS 秒的画面，
    直接首尾相接会把这一小段动作重演一次（接缝处“倒退一下”）。所以下一段是续接段时，上一段末尾剪掉这么多。
    段太短（不到偏移的 4 倍）时不剪；最后一段不剪。
    """
    from core.prev_frame import PREV_FRAME_OFFSET_SECONDS

    offset = int(round(PREV_FRAME_OFFSET_SECONDS * 1_000_000))
    out = []
    for i, dur in enumerate(durations_us):
        nxt = shots[i + 1] if i + 1 < len(shots) else None
        cut = bool(nxt and (nxt or {}).get("prev_frame_attached")) and int(dur or 0) > offset * 4
        out.append(offset if cut else 0)
    return out
