"""多句视频段的配音：逐句生成后，按段内时间拼成一条音频（句间留白）。

用系统里已有的 ffmpeg / ffprobe（视频截帧也在用），不引入新依赖。
"""
import json
import logging
import subprocess
import tempfile
from pathlib import Path
from typing import List

logger = logging.getLogger(__name__)

MIN_GAP = 0.15   # 实际配音比预估长、挤到下一句时，至少留这么多秒的空


def probe_seconds(path: str) -> float:
    """音频时长（秒）。"""
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
                       capture_output=True, text=True, timeout=30)
    try:
        return float(json.loads(r.stdout)["format"]["duration"])
    except Exception as e:  # noqa: BLE001
        raise ValueError(f"读不到音频时长: {r.stderr.strip()[:200]}") from e


def plan_placements(starts: List[float], clip_seconds: List[float]) -> List[float]:
    """每句的实际起点：尽量按段内起点 start 放；前一句的实际配音更长时顺延，保证不重叠。"""
    out, prev_end = [], 0.0
    for start, secs in zip(starts, clip_seconds):
        t = max(float(start or 0), prev_end + (MIN_GAP if out else 0.0))
        out.append(round(t, 3))
        prev_end = t + secs
    return out


def mix_lines(clips: List[bytes], starts: List[float], total_seconds: float) -> tuple:
    """把逐句音频放到各自起点，拼成一条 mp3（不足段时长用静音补齐）。

    返回 (mp3 字节, [{start, end}] 每句实际起止)。
    """
    if not clips:
        raise ValueError("没有可拼接的音频")
    with tempfile.TemporaryDirectory(prefix="dongai-tts-") as tmp:
        paths = []
        for i, data in enumerate(clips):
            p = Path(tmp) / f"line{i}.mp3"
            p.write_bytes(data)
            paths.append(p)
        secs = [probe_seconds(p) for p in paths]
        placed = plan_placements(starts, secs)
        total = max(float(total_seconds or 0), placed[-1] + secs[-1])
        inputs, filters = [], []
        for i, (p, t) in enumerate(zip(paths, placed)):
            inputs += ["-i", str(p)]
            ms = int(round(t * 1000))
            filters.append(f"[{i}:a]aresample=44100,aformat=channel_layouts=mono,adelay={ms}|{ms}[a{i}]")
        mix_in = "".join(f"[a{i}]" for i in range(len(paths)))
        # 各句不重叠，normalize=0 保持原音量；apad + atrim 补齐到段时长
        filters.append(f"{mix_in}amix=inputs={len(paths)}:normalize=0:dropout_transition=0,"
                       f"apad=whole_dur={total:.3f},atrim=0:{total:.3f}[out]")
        out = Path(tmp) / "mix.mp3"
        cmd = ["ffmpeg", "-y", "-v", "error", *inputs, "-filter_complex", ";".join(filters),
               "-map", "[out]", "-ac", "1", "-b:a", "128k", str(out)]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if r.returncode != 0 or not out.exists():
            raise ValueError(f"音频拼接失败: {r.stderr.strip()[:300]}")
        timeline = [{"start": round(t, 2), "end": round(t + d, 2)} for t, d in zip(placed, secs)]
        return out.read_bytes(), timeline
