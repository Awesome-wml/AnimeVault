"""本地 ffmpeg 工具：优先用 venv 内置的 imageio-ffmpeg 二进制，回落系统 PATH。

不依赖系统单独安装 ffmpeg/ffprobe：
- ffmpeg 取自 imageio_ffmpeg 自带的平台二进制；
- 时长探测用 `ffmpeg -i` 解析 stderr 里的 Duration，替代 ffprobe。
"""
import logging
import re
import shutil
import subprocess
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_CACHED_EXE: Optional[str] = None
_DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d+):([\d.]+)")


def ffmpeg_exe() -> str:
    """返回可用的 ffmpeg 可执行路径（内置优先，找不到再回退 PATH）。"""
    global _CACHED_EXE
    if _CACHED_EXE:
        return _CACHED_EXE
    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if Path(exe).exists():
            _CACHED_EXE = exe
            return exe
    except Exception:  # noqa: BLE001
        pass
    _CACHED_EXE = shutil.which("ffmpeg") or "ffmpeg"
    return _CACHED_EXE


def probe_seconds(path) -> float:
    """媒体时长（秒）；用内置 ffmpeg -i 解析，替代 ffprobe。"""
    r = subprocess.run([ffmpeg_exe(), "-hide_banner", "-i", str(path)],
                       capture_output=True, text=True, timeout=30)
    m = _DURATION_RE.search(r.stderr or "")
    if not m:
        raise ValueError(f"读不到媒体时长: {(r.stderr or '')[-200:]}")
    h, mm, ss = m.groups()
    return int(h) * 3600 + int(mm) * 60 + float(ss)


def grab_last_frame(video_path, out_png, offset: str = "-0.5") -> bool:
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
