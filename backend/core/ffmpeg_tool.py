"""本地 ffmpeg 工具：路径解析统一走 core.ffmpeg_locator（env → 随包 bin → PATH）。

时长探测用 `ffmpeg -i` 解析 stderr 里的 Duration，不依赖 ffprobe。
"""
import logging
import re
import subprocess
from pathlib import Path
from core.ffmpeg_locator import ffmpeg_path

logger = logging.getLogger(__name__)

_DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d+):([\d.]+)")
_VIDEO_SIZE_RE = re.compile(r"Stream #.*?Video:.*?(\d{2,5})x(\d{2,5})")


def ffmpeg_exe() -> str:
    """ffmpeg 路径，统一走 ffmpeg_locator（env → 随包 bin → PATH）。"""
    return ffmpeg_path()


def probe_seconds(path) -> float:
    """媒体时长（秒）；用内置 ffmpeg -i 解析，替代 ffprobe。"""
    r = subprocess.run([ffmpeg_exe(), "-hide_banner", "-i", str(path)],
                       capture_output=True, text=True, timeout=30)
    m = _DURATION_RE.search(r.stderr or "")
    if not m:
        raise ValueError(f"读不到媒体时长: {(r.stderr or '')[-200:]}")
    h, mm, ss = m.groups()
    return int(h) * 3600 + int(mm) * 60 + float(ss)


def probe_video(path) -> tuple:
    """(时长秒, 宽, 高)；读不到的项为 None。只调一次 ffmpeg -i。"""
    r = subprocess.run([ffmpeg_exe(), "-hide_banner", "-i", str(path)],
                       capture_output=True, text=True, timeout=30)
    err = r.stderr or ""
    seconds = width = height = None
    m = _DURATION_RE.search(err)
    if m:
        h, mm, ss = m.groups()
        seconds = int(h) * 3600 + int(mm) * 60 + float(ss)
    m = _VIDEO_SIZE_RE.search(err)
    if m:
        width, height = int(m.group(1)), int(m.group(2))
    return seconds, width, height


def grab_last_frame(video_path, out_png, offset: str = "-0.5") -> bool:  # 偏移与 core.prev_frame.PREV_FRAME_OFFSET_SECONDS 一致
    """截视频最后 offset 秒的一帧存为 PNG；成功返回 True。"""
    out_png = Path(out_png)
    out_png.parent.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(
            [ffmpeg_exe(), "-y", "-sseof", offset, "-i", str(video_path),
             "-frames:v", "1", str(out_png)],
            capture_output=True, timeout=15,
        )
        return out_png.exists()
    except Exception as e:  # noqa: BLE001
        logger.debug("截尾帧失败: %s", e)
        return False
